package taskfloor.admission

default allow := false

default require_approval := false

governed_effects := {
  "external_write",
  "destructive",
  "financial",
  "identity",
  "sensitive",
  "privileged",
}

state_bound if {
  input.action.expected_state_id == input.state.state_id
}

approval_bound if {
  input.approval.decision == "approve"
  input.approval.state_id == input.state.state_id
  input.approval.action_sha256 == input.action.action_sha256
  input.approval.effect == input.action.effect
}

preauthorized if {
  input.action.effect in input.cartridge.effect_policy.preauthorized_effects
}

require_approval if {
  input.action.effect in governed_effects
}

require_approval if {
  input.action.effect in input.cartridge.effect_policy.approval_effects
}

allow if {
  state_bound
  preauthorized
}

allow if {
  state_bound
  require_approval
  approval_bound
}

reasons contains "stale action" if {
  not state_bound
}

reasons contains "governed effect lacks a bound approval" if {
  state_bound
  require_approval
  not approval_bound
}
