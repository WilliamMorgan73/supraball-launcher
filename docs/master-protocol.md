# Supraball master server protocol (as used for costumes)

Learned from a capture of the official launcher's traffic (`tools/capture_official.py`, 2026-10-27,
master version field 477). Only the parts this launcher uses are confirmed; everything else is noted
as seen.

## Endpoints

| Port | Protocol | Used for |
|---|---|---|
| `master.supraball.net:8991` | HTTP, `GET /list` | Public server list (JSON). `getPlayerInfo` exists but returns an empty profile for every player. |
| `master.supraball.net:8992` | TCP, framed protobuf | Launcher lobby: sign-in, costumes, profiles, matchmaking. |

## Framing (port 8992)

Every message, both directions:

```
u16 LE  packet id     client picks increasing ids; replies echo the request id; pushes use 0
u8      packet type   numbering differs per direction
u32 LE  body length
bytes   protobuf body (lite runtime, no schema shipped; field numbers below)
```

On connect, the server sends type 33 `{2: 477}` (likely the protocol version).

## Sign-in

Client type 0, Authenticate:

| Field | Value |
|---|---|
| 1 | Steam Encrypted App Ticket for app 321400 (raw bytes) |
| 2 | Steam persona name |
| 4 | Two-letter IP country from Steam (`ISteamUtils::GetIPCountry`) |
| 6 | Launcher version string, `"1.0.0"` |
| 7 | `0` |

Reply: type 7, Response `{1: 0, 2: "Authentication succeeded!"}`. A non-zero field 1 is an error code, with the message in field 2.

## Costumes

Items are Steam Inventory items. The protocol identifies them by **Steam item definition id**.
Names, slots (`item_slot`: `skin`, `hat`, `gun`) and icons come from the definitions via `ISteamInventory`.
`tools/steamhelper` reads them.

- Client type 29, GetAssetConfigs, empty body.
  Reply type 31: repeated field 1 = `{1: definition id, 3: equipped (1/0)}`.
- Client type 28, ChangeAssetConfig `{1: definition id, 3: 1 to equip / 0 to unequip}`.
  Reply type 7 `{1: 0}` on success. The server keeps one item per slot: equipping a hat replaces the current hat.

## Other traffic seen (not used)

| Direction | Type | Contents |
|---|---|---|
| Client | 1 | `{1: 3}` |
| Client | 2 | `{3: 1}` (status/presence) |
| Client | 11 | GetUserInfo: repeated Steam ids plus flags |
| Client | 15 | Team info by id |
| Client | 20, empty | Keep-alive every 10 s; server answers type 18 |
| Server | 1 | Lobby/server list (ip, port, map, name, version, query port) |
| Server | 8 | Player profile (Steam id, XP, per-mode ratings) |
| Server | 14 | User info |
| Server | 15 | Team |
| Server | 20 | Player stats |
| Server | 32 | Regions |
| Server | 35 | Level rewards |
| Server | 37 | Daily reward status |
