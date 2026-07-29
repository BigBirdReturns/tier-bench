# OSS, community, and commodity sweep

## Finding

AXM is not the first project to want a room full of meaningful controls, multiple operator stations, physical and software substitutes, distributed state, local feedback, device reconnection, authored procedures, or replayable hardware tests. At least six communities have independently converged on those needs: spaceship-bridge operators, flight-simulator cockpit builders, show-control and immersive-installation engineers, escape-room and museum builders, robotics and hardware-in-the-loop laboratories, and assistive/custom-controller developers.

The repeated demand is therefore established. The market and community failure is fragmentation. Each community generally solved the lower layers inside its own vertical domain. A flight-simulator mapping names aircraft addresses. A show-control tool names OSC or DMX paths. A robotics controller claims hardware interfaces. A home-automation system names entities. A bridge simulator owns its own stations and world state. Those are valuable supplier products, but none should be allowed to become the authority that defines AXM semantic actions, cartridge law, actor mandates, ownership epochs, accepted consequences, or canonical run custody.

Estate Lab now records that distinction in `fixtures/commodities.example.json`, format `axm-commodity-catalog/1`. Each candidate is assigned one disposition:

- `consume`: use unchanged behind a public contract;
- `adapt`: keep external and translate through an AXM-owned adapter;
- `reference`: harvest design and test evidence without a runtime dependency;
- `reject`: retain the refusal so a retired or unsafe option is not repeatedly rediscovered.

The catalog is content-addressed. Every consumed or adapted supplier names a substitution test. Every adapted supplier names its required adapter. Every candidate states what authority it may not acquire. Version 0.3 expands the ledger to 81 candidates across 27 categories: 18 are consumed as narrow standards or permissive commodities, 37 require AXM-owned adapters, 25 remain references, and one retired dependency remains rejected.

## The standards seam that was still missing

The first sweep found implementations. The wider sweep found the public interoperability and governance substrate that lets those implementations meet at one floor. CloudEvents supplies common event metadata. AsyncAPI supplies a generated event-driven contract. W3C Trace Context and OpenTelemetry supply correlation conventions. W3C Web of Things and Sparkplug supply device-description and lifecycle patterns. The WebAssembly Component Model and WIT supply a sandboxed language-neutral boundary. OCI and ORAS supply artifact distribution. Sigstore, SLSA, in-toto, SPDX, CycloneDX, and TUF supply complementary release, provenance, inventory, and update evidence. JSON Schema supplies portable structural validation. MCP and A2A supply agent transport surfaces. Kubernetes conformance and Home Assistant's Integration Quality Scale supply public certification and integration-quality governance precedents.

None of those standards should become a second semantic authority. They are consumed or adapted as projections around `axm-interaction-request/1`, `axm-semantic-event/1`, `axm-interaction-response/1`, and the public conformance submission. The floor specification and vectors remain the narrow waist.

## Community map

### Bridge simulators and educational installations

Thorium Nova, Thorium Classic, EmptyEpsilon, and Space Nerds In Space demonstrate sustained demand for distributed stations, a game or flight director, join and reconnect behavior, scenario authoring, hardware clients, lighting, sound, video, and same-room multi-crew play. Thorium is especially close to the product shape: it explicitly describes a distributed, fault-tolerant show-control system whose external hardware panels use the same client mechanisms as crew stations.

These projects are not dependencies for AXM law. They are design and acceptance corpora. Their station taxonomies, flight-director workloads, onboarding mistakes, reconnect behavior, failure cases, and event-operation practices should become comparative Estate Lab fixtures.

### Flight and home cockpit builders

DCS-BIOS, MobiFlight, CockpitOS, OpenHornet, OpenDeck, QMK, and OpenFFBoard prove that the physical-panel problem is already a substantial maker ecosystem. The community has mature solutions for control metadata, binary state streams, commands, replay, visual mapping tools, buttons, encoders, analog inputs, LEDs, segment displays, TFTs, stepper gauges, force feedback, USB HID, WiFi, BLE, serial, and RS485.

CockpitOS is particularly important because it independently reproduces much of the Enigma edge architecture: static memory, nonblocking I/O, selective subscriptions, generated label sets, transport abstraction, high-rate input polling, debug recording, replay, and native ESP32-S2/S3 USB. MobiFlight demonstrates that no-code configuration and shared presets can support a large community. DCS-BIOS demonstrates a durable metadata and replay seam. We should test these as suppliers before writing equivalent device drivers or authoring tools ourselves.

### Show control, immersive theatre, museums, and escape rooms

Bitfocus Companion, QLC+, Open Stage Control, ossia score, OLA, OpenFollow, MoonLight, Node-RED, Realix, ARC, Open Exhibits, ParadisePi, and OpenAVC show another mature lineage. These communities already operate distributed button surfaces, variable feedback, lighting protocols, timeline cues, tracking, zone events, room resets, audit logs, props, locks, projectors, media, and heterogeneous devices.

The useful transfer is operational. These systems know how to keep a room running, let an operator intervene, display feedback, reset between groups, route around a failed device, and integrate long-tail equipment. Their weakness for AXM is that patch graphs, cue timelines, macros, and button pages can quietly become hidden domain law. The adapter must therefore expose exact inputs and desired outputs while keeping causal game and procedure logic in the cartridge and deterministic engine.

### Robotics, hardware-in-the-loop, and board farms

ROS 2 control, OpenHTF, labgrid, Zephyr Twister, Renode, Eclipse openDuT, OpenHiL, and Eclipse OpenXilEnv establish that software twins, mock hardware, exclusive command ownership, board farms, fixture drivers, test phases, measurements, attachments, flashing, power cycling, reconnect tests, and mixed physical/virtual devices are mature engineering categories.

This is the strongest evidence that Estate Lab should not grow its own board scheduler or manufacturing-style test framework. The correct split is to let these tools acquire resources and execute bounded physical phases, then translate their measurements and attachments into Estate Lab receipts. A PASS in an upstream test runner is still not AXM acceptance. The AXM burden, verifier, authority, and evidence tier remain explicit.

### Telemetry, replay, and mission operations

MCAP, Foxglove, and NASA Open MCT demonstrate mature separation between high-volume timestamped streams and operator visualization. MCAP is the most immediate commodity. It is a schema-carrying, indexed, append-oriented log format with independent readers. AXM should use it for raw device reports, poses, sensor streams, audio events, and simulation telemetry while retaining canonical semantic events and accepted consequences in existing AXM records.

Foxglove and Open MCT should be adapters, not authorities. They can provide deep technical replay, plots, timelines, three-dimensional views, procedures, and mission-control layouts. A standalone AXM report and independent MCAP reader remain the substitution fallback.

### Digital twins and distributed state

MQTT 5, OSC, OSCQuery, Eclipse Ditto, Eclipse BaSyx, and Zenoh demonstrate desired versus reported state, retained state, persistent sessions, discovery, query, storage, and heterogeneous transport. The transport question is therefore measurable rather than ideological. MQTT 5 should be the conservative asynchronous baseline. OSC and OSCQuery should serve media and show-control boundaries. Zenoh should enter Supplier Foundry as a candidate only when a declared latency, discovery, or query workload exceeds the MQTT baseline. Ditto and BaSyx are optional projections for deployed-fleet interoperability, not canonical run stores.

### Input abstraction and assistive control

OpenXR, SDL, Unity Input System, OpenTrack, FreePIE, Joypad OS, QMK, ZMK, OpenDeck, and OpenFFBoard show sustained demand for semantic actions, device rebinding, controller mappings, pose filtering, virtual input, assistive controllers, haptics, and custom hardware. OpenXR's action model, SDL's gamepad mapping, and Unity's event traces should carry device-level bindings. Estate Lab and AXM Embodied must continue to own source confidence, lease and ownership transfer, role and mandate checks, and fail-closed loss of control.

## Acquisition order

### P0: stop rebuilding these layers

The first acquisition train is:

1. JSON Schema, CloudEvents, AsyncAPI, W3C Trace Context, and the floor command binding for public protocol and contract interoperability.
2. OCI artifact layouts, SLSA, SPDX, and CycloneDX for portable release, provenance, and inventory evidence.
3. TinyUSB for device-side USB and HIDAPI for host-side HID discovery and reports.
4. OpenXR actions, SDL gamepad mappings, and Unity Input System event traces for physical input normalization.
5. MCAP for raw timestamped stream custody.
6. MQTT 5 for asynchronous device sessions and retained desired/reported state.
7. DCS-BIOS, MobiFlight, and CockpitOS as panel-metadata, configuration, replay, and firmware suppliers.
8. WLED, OLA, and Bitfocus Companion as replaceable output and operator-surface appliances.
9. OpenHTF and labgrid as physical test and board-resource suppliers.
10. Node-RED only as a bounded adapter host for long-tail protocols.

Each enters through a supplier qualification rather than an architectural migration. The original source, semantic declaration, replay vectors, and independent verifier must survive removal of the supplier.

### P1: build adapters after the P0 contracts stabilize

The second train covers LVGL, QLC+, Open Stage Control, ossia score, OpenTrack, Foxglove, Open MCT, Zephyr Twister, Renode, ROS 2 control, Eclipse Ditto, and OSCQuery. These deliver high value once AXM action, output, stream, and physical-test contracts are stable enough to prevent upstream vocabulary from becoming law.

### P2 and P3: retain as alternatives and stressors

The remaining projects are valuable as alternatives, design references, community contacts, and adversarial fixtures. They should not expand the first integration surface. Their purpose is to prevent local optimization around one supplier and to preserve options if a chosen upstream declines, relicenses, becomes unmaintained, or fails a new workload.

## What remains differentiated

The commodity sweep removes any credible claim that distributed controls, cockpit panels, software twins, show control, reconnect handling, replay, or HIL testing are unique inventions. The differentiated AXM layer is the combination that the vertical communities do not generally provide together:

- one semantic action identity across browser, screen procedure, gamepad, XR, agent, and physical device;
- explicit actor, role, mandate, and ownership epoch before mutation;
- cartridge-owned law and deterministic consequences independent of embodiment;
- desired-output projection separated from state authority;
- content-derived run and receipt identities;
- supplier admission, substitution, fallback, and rip-out evidence;
- one estate-wide routing instrument that can compare physical, software, human, and agent paths without allowing the router to decide what the action means.

That layer should remain small. Everything below it should become a measured supplier wherever an upstream contract can satisfy the burden.

## Required next fixtures

The catalog is a reviewed decision ledger, not proof that any upstream works for AXM. Estate Lab should add the following executable supplier families:

1. `floor.binding.roundtrip/v1`: command JSON, CloudEvents, MQTT 5, WebSocket, and WIT bindings recover the same request, response, and conformance identities.
4. `floor.release.resurrection/v1`: OCI, SPDX, CycloneDX, SLSA, and an independent verifier recover a floor release without Git or hosted services.
5. `usb.hid.roundtrip/v1`: TinyUSB device plus HIDAPI host, enumeration, feature reports, unplug, reconnect, and duplicate delivery.
4. `panel.mapping.translate/v1`: one MobiFlight configuration and one CockpitOS label set compiled into the same AXM surface declaration.
5. `light.desired-output/v1`: WLED, OLA/QLC+, and a software twin driven by one exact desired-light program.
6. `operator.surface/v1`: Bitfocus Companion and the AXM browser twin driven by one button and feedback declaration.
7. `stream.custody.mcap/v1`: Python and TypeScript writers/readers producing cross-readable raw-event streams with exact payload identity.
8. `device.session.mqtt5/v1`: retained state, session expiry, reconnect, duplicate delivery, and idempotent reducer behavior against two brokers.
9. `physical.commission/v1`: OpenHTF phases over a labgrid-managed board, including flash, calibration, I/O, disconnect, reconnect, and replay.
10. `xr.binding/v1`: OpenXR and Unity action bindings producing the same normalized action and ownership-loss behavior.
11. `telemetry.visualization/v1`: Foxglove, Open MCT, and the standalone report reconstructing the same selected series and event counts.
12. `transport.frontier/v1`: MQTT 5 versus Zenoh under declared LAN loss, latency, discovery, and query workloads.

The controlling question is whether every lower layer can be replaced while the semantic action, authority result, committed state, desired outputs, replay evidence, and causal debrief remain reproducible without that supplier.
