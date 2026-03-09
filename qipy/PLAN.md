# qipy — Pure Python 3 QiMessaging Bindings

## Goal

Replace the Python 2 bridge with a pure Python 3 implementation of the QiMessaging protocol, connecting directly to NAOqi over TCP port 9559. No C extensions, no Python 2 dependency, works with any Python 3.5+.

## Protocol Summary

QiMessaging is a binary RPC protocol over TCP. Reference: [qiloop docs](https://github.com/lugu/qiloop), [libqi source](https://github.com/aldebaran/libqi).

### Message Header (28 bytes)

```
Offset  Size  Field         Endian
0       4     magic         big-endian    0x42dead42
4       4     id            little-endian message counter
8       4     size          little-endian payload size in bytes
12      4     version       little-endian 0
16      4     type          little-endian see below
20      4     flags         little-endian 0
24      4     service       little-endian target service ID
28      4     object        little-endian target object ID
32      4     action        little-endian method index
```

Note: header is actually 36 bytes total (28 was from partial docs — the full header has service/object/action fields). Will verify against libqi source during implementation.

### Message Types

| Value | Type       | Direction      |
|-------|------------|----------------|
| 1     | Call       | client → robot |
| 2     | Reply      | robot → client |
| 3     | Error      | robot → client |
| 4     | Post       | client → robot (fire-and-forget) |
| 5     | Event      | robot → client |
| 6     | Capability | both           |
| 7     | Cancel     | client → robot |
| 8     | Cancelled  | robot → client |

### Type Signatures

| Char | Type     | Serialization |
|------|----------|---------------|
| `b`  | bool     | 1 byte (0/1) |
| `i`  | int32    | 4 bytes LE |
| `I`  | uint32   | 4 bytes LE |
| `l`  | int64    | 8 bytes LE |
| `L`  | uint64   | 8 bytes LE |
| `f`  | float32  | 4 bytes LE |
| `d`  | float64  | 8 bytes LE |
| `s`  | string   | uint32 length + UTF-8 bytes |
| `r`  | raw      | uint32 length + bytes |
| `v`  | dynamic  | signature string + value |
| `o`  | object   | MetaObject + service/object IDs |
| `[X]`| list     | uint32 count + count × X |
| `{XY}`| map     | uint32 count + count × (key X + value Y) |
| `(XY…)`| tuple  | X then Y then … (no length prefix) |

### Authentication Handshake

1. Client connects TCP to port 9559
2. Robot sends CapabilityMap message (type 6) listing supported auth mechanisms
3. Client replies with CapabilityMap: `{"auth_user": "nao", "auth_token": "nao"}`
4. Robot replies with CapabilityMap containing `__qi_auth_state`: 3 = success

### Service Directory (service 1)

| Action | Method        | Signature        | Returns |
|--------|---------------|------------------|---------|
| 100    | service       | (s) → ServiceInfo | info for named service |
| 101    | services      | () → [ServiceInfo] | all services |
| 102    | registerService | (ServiceInfo) → I | register |
| 103    | unregisterService | (I) → v | unregister |
| 104    | serviceReady  | (I) → v | signal |
| 108    | machineId     | () → s | machine UUID |

ServiceInfo struct: `(IsIss[s])` — name, serviceId, machineId, processId, endpoints, object UIDs.

### MetaObject (action 2 on any object)

Returns the method/signal/property table for introspection. Struct contains maps of:
- methods: `{I(IssI[(ss)]s)}` — uid → (uid, returnSig, name, id, params[(name,sig)], description)
- signals: `{I(Iss[(ss)]s)}` — uid → (uid, name, sig, params, description)
- properties: `{I(Iss[(ss)]s)}` — uid → (uid, name, sig, params, description)
- description: `s`

---

## Architecture

```
qipy/
├── __init__.py          # public API: Session, connect()
├── protocol.py          # header encode/decode, message framing
├── serialization.py     # type signature parser, serialize/deserialize values
├── session.py           # TCP connection, auth, message dispatch
├── service_directory.py # service lookup, caching
├── proxy.py             # ServiceProxy with __getattr__ magic
├── meta.py              # MetaObject parsing, method signature lookup
└── errors.py            # QiError, ConnectionError, etc.
```

No external dependencies. Uses only stdlib: `socket`, `struct`, `threading`, `json` (for debug only).

---

## Implementation Plan

### Phase 1: Wire Protocol

**File: `protocol.py`**

1. Define `Header` namedtuple with fields: magic, id, size, version, type, flags, service, object, action
2. `encode_header(header) → bytes` — pack 9 uint32s (magic big-endian, rest little-endian)
3. `decode_header(data: bytes) → Header` — unpack 36 bytes
4. `MessageType` enum: Call=1, Reply=2, Error=3, Post=4, Event=5, Capability=6, Cancel=7, Cancelled=8
5. `read_message(sock) → (Header, bytes)` — read 36-byte header, then `size` bytes of payload
6. `write_message(sock, header, payload)` — send header + payload

**Validation**: Connect to pepper:9559 with raw socket, read the first message (should be a Capability message from the robot). Print hex dump.

### Phase 2: Serialization

**File: `serialization.py`**

1. `parse_signature(sig: str) → TypeNode` — recursive descent parser for type signatures
   - TypeNode: `Atom(char)`, `List(inner)`, `Map(key, value)`, `Tuple(members)`, `Dynamic()`, `Object()`
2. `serialize(value, sig: str) → bytes` — encode Python value according to signature
3. `deserialize(data: bytes, sig: str) → (value, remaining_bytes)` — decode bytes to Python value
4. Special handling:
   - `v` (dynamic): write signature string then serialize the value with that signature
   - `o` (object): deserialize MetaObject + IDs, return proxy
   - `r` (raw): bytes passthrough
   - Strings: length-prefixed UTF-8
   - Lists/maps: count-prefixed

**Validation**: Round-trip test — serialize then deserialize basic types, lists, maps, nested structures.

### Phase 3: Authentication & Connection

**File: `session.py`**

1. `Session` class:
   - `connect(url='tcp://192.168.11.182:9559')` — parse URL, open TCP socket
   - Internal message ID counter (atomic)
   - Pending calls dict: `{msg_id: Future}`
   - Receiver thread: reads messages in a loop, dispatches replies to futures
2. Auth flow:
   - Receive robot's CapabilityMap (type 6, service 0, action 0)
   - Deserialize capability map (type `{sv}` — map of string to dynamic)
   - Send our CapabilityMap with `auth_user`/`auth_token`
   - Receive auth response, check `__qi_auth_state == 3`
3. `call(service, object, action, sig, *args) → value` — build Call message, serialize args, send, wait for Reply
4. `post(service, object, action, sig, *args)` — fire-and-forget

**Validation**: Connect to pepper, authenticate, call service 1 action 108 (machineId), print result.

### Phase 4: Service Directory

**File: `service_directory.py`**

1. `ServiceDirectory` class wrapping service 1:
   - `service(name) → ServiceInfo` — call action 100
   - `services() → [ServiceInfo]` — call action 101
2. Parse ServiceInfo struct `(IsIss[s])`
3. Cache service name → (serviceId, endpoint) mapping

**Validation**: List all services on pepper, print names and IDs.

### Phase 5: MetaObject & Proxy

**File: `meta.py`**

1. `MetaObject` class:
   - Parse the introspection struct returned by action 2
   - `find_method(name) → (action_id, param_sig, return_sig)`
   - `find_signal(name) → (signal_id, sig)`
   - `find_property(name) → (prop_id, sig)`

**File: `proxy.py`**

2. `ServiceProxy` class:
   - Created by `session.service(name)`
   - On first access, fetches MetaObject via action 2
   - `__getattr__(method_name)` returns a callable that:
     - Looks up method in MetaObject
     - Serializes args according to parameter signature
     - Sends Call message
     - Deserializes Reply according to return signature
   - Signal subscription via `proxy.signal_name.connect(callback)`

**File: `__init__.py`**

3. Public API:
   ```python
   from qipy import Session

   session = Session()
   session.connect('tcp://192.168.11.182:9559')
   tts = session.service('ALTextToSpeech')
   tts.say('Hello from pure Python 3!')
   session.close()
   ```

**Validation**: Call `ALTextToSpeech.say()`, `ALSystem.systemVersion()`, `ALMotion.getJointNames('Body')`.

### Phase 6: Signals & Events

1. Subscribe to signals via service 0 action `registerEvent` or object-level signal connect
2. Receiver thread dispatches Event messages (type 5) to registered callbacks
3. API: `proxy.signal_name.connect(callback)` / `.disconnect(id)`

**Validation**: Subscribe to `ALMemory.subscriber("WordRecognized")`, print events.

### Phase 7: Polish

1. Context manager: `with Session() as s: ...`
2. Reconnection logic (optional)
3. Proper socket cleanup and thread shutdown
4. Timeout on calls (default 10s)
5. Logging via stdlib `logging`
6. `__repr__` on proxies showing service name and available methods

---

## Testing Strategy

### On dev machine (no robot needed)

- Unit tests for `protocol.py`: header encode/decode round-trip
- Unit tests for `serialization.py`: all type signatures, edge cases (empty list, nested map, dynamic)
- Mock TCP server for auth handshake tests

### On pepper (integration)

- Connect, authenticate, get machine ID
- List services
- Call simple methods: `ALSystem.systemVersion()`, `ALTextToSpeech.say()`
- Call methods with complex args: `ALMotion.setAngles(['HeadYaw'], [0.5], 0.2)`
- Call methods with complex returns: `ALMotion.getJointNames('Body')` → list of strings
- Verify error handling: call nonexistent service, call with wrong args

---

## Open Questions

1. **Exact header size**: docs say 28 bytes but that excludes service/object/action fields. Need to verify against libqi source or wire capture. The qiloop Go implementation is the most reliable reference.
2. **CapabilityMap serialization**: the capability map uses type signature `{sv}` (map of string to dynamic value). Need to verify exact encoding.
3. **Signal protocol**: signal subscription may require registering with service 0 or calling a method on the service object. Need to trace from libqi or qiloop.
4. **Object references**: when a method returns an object (`o` type), how to route subsequent calls — via the original service endpoint or a new connection?
5. **Concurrent calls**: verify that the robot handles multiple in-flight Call messages and matches replies by message ID.

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Header format wrong | Capture actual traffic with tcpdump on pepper, compare with our encoding |
| Auth fails | Fall back to no-auth (some NAOqi versions allow unauthenticated local connections) |
| Complex type serde bugs | Start with simple types, add complexity incrementally, test each against real robot responses |
| Signal protocol unclear | Defer signals to phase 6, core RPC works without them |
| Performance | Pure Python will be slower than C bindings but adequate for robot control (latency budget is ~100ms for motion commands) |

---

## References

- [QiMessaging protocol (qiloop docs)](https://github.com/lugu/qiloop)
- [libqi source (C++)](https://github.com/aldebaran/libqi)
- [qiloop Go implementation](https://github.com/lugu/qiloop) — most readable reference implementation
- [NAOqi 2.5 API docs](http://doc.aldebaran.com/2-5/)
