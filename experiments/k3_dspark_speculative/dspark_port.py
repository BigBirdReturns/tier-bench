"""Plain-torch port of vLLM's K3DSpark draft model (Windows, no vLLM).

Ported from vllm-project/vllm @ 94a54f581e16 (sources archived in
estate/k3-dspark-morning-launch-20260828/reference/):
  - vllm/models/kimi_k3/nvidia/dspark_mla.py  (model structure, context KV)
  - vllm/models/kimi_k3/nvidia/mla.py          (MLA geometry, yarn scale)
  - vllm/model_executor/models/qwen3_dspark.py (Markov + confidence heads)
  - vllm/v1/spec_decode/dflash.py + utils kernel (query layout, positions)
  - deepseek_scaling_rope.py                   (yarn rotary, is_neox=False)

Faithfulness notes (recorded, not hidden):
  - Naive decompressed MLA attention (q/k/v materialized per head) instead of
    vLLM's latent-cache absorbed kernels - mathematically equivalent form.
  - Softmax scale = (128+64)**-0.5 * mscale^2, mscale = 0.1*mscale_all_dim*
    ln(factor)+1 = 1.34657 (deepseek_yarn path; config declares yarn and
    apply_yarn_scaling is absent -> True). A no_yarn_scale flag exists because
    a vLLM comment suggests the draft may run the default rope; the yarn path
    is the config-faithful default.
  - The checkpoint ships NO lm_head (vLLM aliases the frozen target's);
    K3's language_model.lm_head.weight must be provided. embed_tokens ships
    in-checkpoint (frozen target embedding).
  - Proposal-time layout per the dflash proposer: queries = [bonus token,
    mask x K] at positions last_ctx_pos+1..+1+K, fully non-causal, attending
    over per-layer context KV projected from combined target states.
  - This port proves interface viability and produces proposals; it is NOT
    the official implementation. K3 adjudicates every committed token, so
    port infidelity can only depress acceptance, never corrupt output.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import torch
import torch.nn.functional as F

MODEL_DIR = Path(r"D:\kimilab\models\Kimi-K3-DSpark")


# ---------------------------------------------------------------- yarn rope
def _yarn_correction_dim(num_rot: float, dim: int, base: float, max_pos: int) -> float:
    return (dim * math.log(max_pos / (num_rot * 2 * math.pi))) / (2 * math.log(base))


def _yarn_correction_range(low_rot: float, high_rot: float, dim: int, base: float,
                           max_pos: int) -> tuple[int, int]:
    low = math.floor(_yarn_correction_dim(low_rot, dim, base, max_pos))
    high = math.ceil(_yarn_correction_dim(high_rot, dim, base, max_pos))
    return max(low, 0), min(high, dim - 1)


def _yarn_ramp(low: float, high: float, dim: int) -> torch.Tensor:
    if low == high:
        high += 0.001
    linear = (torch.arange(dim, dtype=torch.float32) - low) / (high - low)
    return torch.clamp(linear, 0, 1)


def yarn_get_mscale(scale: float = 1.0, mscale: float = 1.0) -> float:
    if scale <= 1:
        return 1.0
    return 0.1 * mscale * math.log(scale) + 1.0


class DeepseekYarnRope:
    """cos/sin cache identical to vLLM DeepseekScalingRotaryEmbedding."""

    def __init__(self, rotary_dim: int, base: float, original_max_pos: int,
                 factor: float, beta_fast: float, beta_slow: float,
                 mscale: float, mscale_all_dim: float, device):
        self.rotary_dim = rotary_dim
        pos_freqs = base ** (torch.arange(0, rotary_dim, 2, dtype=torch.float32) / rotary_dim)
        inv_extra = 1.0 / pos_freqs
        inv_inter = 1.0 / (factor * pos_freqs)
        low, high = _yarn_correction_range(beta_fast, beta_slow, rotary_dim, base, original_max_pos)
        mask = 1.0 - _yarn_ramp(low, high, rotary_dim // 2)
        inv_freq = inv_inter * (1 - mask) + inv_extra * mask
        # cos/sin magnitude correction ratio (1.0 when mscale == mscale_all_dim)
        cos_scale = float(yarn_get_mscale(factor, mscale) / yarn_get_mscale(factor, mscale_all_dim))
        t = torch.arange(int(original_max_pos * factor), dtype=torch.float32)
        freqs = torch.einsum("i,j->ij", t, inv_freq)
        self.cos = (freqs.cos() * cos_scale).to(device)
        self.sin = (freqs.sin() * cos_scale).to(device)

    def rotate(self, x: torch.Tensor, positions: torch.Tensor) -> torch.Tensor:
        """GPT-J interleaved rotation (is_neox_style=False), fp32 math.
        x: [n, heads, rotary_dim]; positions: [n]."""
        cos = self.cos[positions].repeat_interleave(2, dim=-1).unsqueeze(-2)
        sin = self.sin[positions].repeat_interleave(2, dim=-1).unsqueeze(-2)
        xf = x.float()
        x1 = xf[..., ::2]
        x2 = xf[..., 1::2]
        rotated = torch.stack((-x2, x1), dim=-1).flatten(-2)
        return (xf * cos + rotated * sin).to(x.dtype)


def rms_norm(x: torch.Tensor, weight: torch.Tensor, eps: float) -> torch.Tensor:
    xf = x.float()
    normed = xf * torch.rsqrt(xf.square().mean(-1, keepdim=True) + eps)
    return (normed * weight.float()).to(x.dtype)


def load_safetensors_cpu(path: Path) -> dict[str, torch.Tensor]:
    from safetensors.torch import load_file

    # direct-to-CUDA load fails on this host (pinned-mmap registration);
    # CPU load + per-tensor move is the admitted path.
    return load_file(str(path))


class K3DSparkPort:
    """Standalone drafter: context KV insertion + one non-causal block pass."""

    def __init__(self, device: str = "cuda:0", model_dir: Path = MODEL_DIR,
                 lm_head: torch.Tensor | None = None, no_yarn_scale: bool = False):
        self.device = device
        cfg = json.loads((model_dir / "config.json").read_text(encoding="utf-8-sig"))
        self.cfg = cfg
        self.num_layers = cfg["num_hidden_layers"]
        self.heads = cfg["num_attention_heads"]
        self.nope = cfg["qk_nope_head_dim"]
        self.rope_dim = cfg["qk_rope_head_dim"]
        self.v_dim = cfg["v_head_dim"]
        self.kv_lora = cfg["kv_lora_rank"]
        self.eps = cfg["rms_norm_eps"]
        self.mask_token_id = cfg["mask_token_id"]
        qk_head_dim = self.nope + self.rope_dim
        rp = cfg["rope_parameters"]
        self.scale = qk_head_dim ** -0.5
        if not no_yarn_scale and rp["rope_type"] == "yarn" and rp["factor"] > 1:
            m = 0.1 * float(rp.get("mscale_all_dim", 0.0)) * math.log(rp["factor"]) + 1.0
            self.scale *= m * m
        self.rope = DeepseekYarnRope(
            self.rope_dim, rp["rope_theta"], rp["original_max_position_embeddings"],
            rp["factor"], rp["beta_fast"], rp["beta_slow"],
            rp.get("mscale", 1.0), rp.get("mscale_all_dim", 0.0), device)
        w = load_safetensors_cpu(model_dir / "model.safetensors")
        self.w = {k: v.to(device) for k, v in w.items()}
        self.lm_head = lm_head.to(device) if lm_head is not None else None
        self._embed_cache: dict[int, torch.Tensor] = {}

    def _target_embed_row(self, token_id: int) -> torch.Tensor:
        if token_id not in self._embed_cache:
            self._embed_cache[token_id] = load_k3_embed_rows([token_id])[0].to(self.device)
        return self._embed_cache[token_id]

    # ------------------------------------------------------------ interfaces
    def combine_hidden_states(self, stacked: torch.Tensor) -> torch.Tensor:
        """[n, 5*7168] concat (target_layer_ids order) -> [n, 7168]."""
        out = F.linear(stacked, self.w["context_proj.weight"])
        return rms_norm(out, self.w["context_norm.weight"], self.eps)

    def _layer_context_kv(self, layer: int, context_states: torch.Tensor,
                          positions: torch.Tensor):
        """Project combined context states into this layer's decompressed K/V."""
        p = f"layers.{layer}"
        kv_a = F.linear(context_states, self.w[f"{p}.self_attn.kv_a_proj_with_mqa.weight"])
        kv_c = rms_norm(kv_a[..., : self.kv_lora],
                        self.w[f"{p}.self_attn.kv_a_layernorm.weight"], self.eps)
        k_pe = self.rope.rotate(kv_a[..., self.kv_lora:].unsqueeze(1), positions)  # [n,1,64]
        kv = F.linear(kv_c, self.w[f"{p}.self_attn.kv_b_proj.weight"])
        kv = kv.view(-1, self.heads, self.nope + self.v_dim)
        k_nope, v = kv[..., : self.nope], kv[..., self.nope:]
        k = torch.cat((k_nope, k_pe.expand(-1, self.heads, -1)), dim=-1)  # [n,h,192]
        return k, v

    def _attention(self, layer: int, x: torch.Tensor, positions: torch.Tensor,
                   ctx_k: torch.Tensor, ctx_v: torch.Tensor) -> torch.Tensor:
        """Queries from x attend over [context ++ queries], fully non-causal."""
        p = f"layers.{layer}"
        q_a = rms_norm(F.linear(x, self.w[f"{p}.self_attn.q_a_proj.weight"]),
                       self.w[f"{p}.self_attn.q_a_layernorm.weight"], self.eps)
        q = F.linear(q_a, self.w[f"{p}.self_attn.q_b_proj.weight"])
        q = q.view(-1, self.heads, self.nope + self.rope_dim)
        q_nope, q_pe = q[..., : self.nope], q[..., self.nope:]
        q_pe = self.rope.rotate(q_pe, positions)
        q = torch.cat((q_nope, q_pe), dim=-1)
        qk, qv = self._layer_context_kv(layer, x, positions)  # queries' own K/V
        k = torch.cat((ctx_k, qk), dim=0)
        v = torch.cat((ctx_v, qv), dim=0)
        scores = torch.einsum("qhd,khd->hqk", q.float(), k.float()) * self.scale
        probs = scores.softmax(-1)
        out = torch.einsum("hqk,khd->qhd", probs, v.float()).to(x.dtype)
        return F.linear(out.reshape(x.shape[0], self.heads * self.v_dim),
                        self.w[f"{p}.self_attn.o_proj.weight"])

    def _mlp(self, layer: int, x: torch.Tensor) -> torch.Tensor:
        p = f"layers.{layer}.mlp"
        gate = F.linear(x, self.w[f"{p}.gate_proj.weight"])
        up = F.linear(x, self.w[f"{p}.up_proj.weight"])
        return F.linear(F.silu(gate) * up, self.w[f"{p}.down_proj.weight"])

    @torch.inference_mode()
    def forward_block(self, context_states: torch.Tensor, context_positions: torch.Tensor,
                      bonus_token: int, num_masks: int = 7) -> torch.Tensor:
        """One draft pass. Returns final hidden states of all query tokens
        [1+num_masks, 7168] (post final_norm)."""
        n_q = 1 + num_masks
        last = int(context_positions.max().item())
        q_positions = torch.arange(last + 1, last + 1 + n_q, device=self.device)
        input_ids = torch.tensor([bonus_token] + [self.mask_token_id] * num_masks,
                                 device=self.device)
        # vLLM aliases the FROZEN TARGET embedding for the draft (the shipped
        # embed_tokens is a trained variant: ~1.10x norms, direction drift on
        # real tokens, mask-token direction preserved - measured 2026-08-28).
        # Serving semantics therefore use K3 target rows, fetched bounded.
        hidden = torch.stack(
            [self._target_embed_row(int(t)) for t in input_ids.tolist()]
        ).to(self.device)
        residual = None
        per_layer_ctx = [self._layer_context_kv(l, context_states, context_positions)
                         for l in range(self.num_layers)]
        for layer in range(self.num_layers):
            p = f"layers.{layer}"
            if residual is None:
                residual = hidden
                x = rms_norm(hidden, self.w[f"{p}.input_layernorm.weight"], self.eps)
            else:
                residual = residual + hidden
                x = rms_norm(residual, self.w[f"{p}.input_layernorm.weight"], self.eps)
            attn = self._attention(layer, x, q_positions, *per_layer_ctx[layer])
            residual = residual + attn
            x = rms_norm(residual, self.w[f"{p}.post_attention_layernorm.weight"], self.eps)
            hidden = self._mlp(layer, x)
        final = rms_norm(residual + hidden, self.w["final_norm.weight"], self.eps)
        return final

    @torch.inference_mode()
    def propose(self, context_states: torch.Tensor, context_positions: torch.Tensor,
                bonus_token: int, num_masks: int = 7) -> dict:
        """Greedy DSpark proposal with sequential Markov bias.

        Returns tokens (len num_masks), per-position scores (chosen logit),
        and confidence per position."""
        if self.lm_head is None:
            raise RuntimeError("K3 lm_head required for logits (checkpoint ships none)")
        final = self.forward_block(context_states, context_positions, bonus_token, num_masks)
        mask_hidden = final[1:]  # sample at the mask positions only
        logits = F.linear(mask_hidden.float(), self.lm_head.float())
        w1, w2 = self.w["markov_head.markov_w1.weight"], self.w["markov_head.markov_w2.weight"]
        conf_w = self.w["confidence_head.proj.weight"].float()
        conf_b = self.w["confidence_head.proj.bias"].float()
        prev = bonus_token
        tokens, scores, confidences = [], [], []
        for i in range(num_masks):
            m_embed = w1[prev].float()                     # [256]
            bias = F.linear(m_embed, w2.float())           # [V]
            row = logits[i] + bias
            pick = int(row.argmax().item())
            conf_in = torch.cat((mask_hidden[i].float(), m_embed))
            confidence = torch.sigmoid(F.linear(conf_in, conf_w) + conf_b)
            tokens.append(pick)
            scores.append(float(row[pick].item()))
            confidences.append(float(confidence.item()))
            prev = pick
        return {"tokens": tokens, "scores": scores, "confidence": min(confidences),
                "per_position_confidence": confidences}


def load_k3_embed_rows(token_ids: list[int]) -> torch.Tensor:
    """Bounded direct read of frozen K3 target embedding rows."""
    root = Path(r"D:\kimilab\Kimi-K3")
    index = json.loads((root / "model.safetensors.index.json").read_text(encoding="utf-8-sig"))
    shard = index["weight_map"]["language_model.model.embed_tokens.weight"]
    with open(root / shard, "rb") as f:
        hlen = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(hlen))
        meta = header["language_model.model.embed_tokens.weight"]
        assert meta["dtype"] == "BF16"
        width = meta["shape"][1]
        rows = []
        for t in token_ids:
            f.seek(8 + hlen + meta["data_offsets"][0] + t * width * 2)
            rows.append(torch.frombuffer(bytearray(f.read(width * 2)), dtype=torch.bfloat16))
    return torch.stack(rows)


def load_k3_lm_head(device: str = "cpu") -> torch.Tensor:
    """Load the frozen target lm_head from the K3 image (bounded direct read)."""
    root = Path(r"D:\kimilab\Kimi-K3")
    index = json.loads((root / "model.safetensors.index.json").read_text(encoding="utf-8-sig"))
    shard = index["weight_map"]["language_model.lm_head.weight"]
    with open(root / shard, "rb") as f:
        hlen = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(hlen))
        meta = header["language_model.lm_head.weight"]
        assert meta["dtype"] == "BF16"
        off0, off1 = meta["data_offsets"]
        f.seek(8 + hlen + off0)
        raw = f.read(off1 - off0)
    flat = torch.frombuffer(bytearray(raw), dtype=torch.bfloat16)
    return flat.view(*meta["shape"]).to(device)
