# Supraball Launcher

A Linux launcher for [Supraball](https://store.steampowered.com/app/321400/) (Steam, run through Proton).

This is an unofficial fan project. It isn't made or endorsed by the Supraball developers.

- **Server browser**: lists public servers from the Supraball master server (`master.supraball.net:8991`)
  with ping, search, and filters. Double-click to join, or use *Connect to IP…*.
- **Host server**: start and stop a dedicated server from a form: map, name, password, mode, bots,
  goal score, time limit, ports. You can keep a server private or list it publicly. Settings can be
  saved as presets, and the server log shows live. The tab tells you whether the master server listed
  your server, and *Check reachability* tells you whether players on the internet are likely to reach you.
- **Play**: starts the game directly, skipping the official launcher.
- **Costume**: shows your player as they'll look in game and lets you change what they wear.
  Hover an item to try it on, then click to wear it. Your Steam Inventory items are listed by slot.
  Changes are saved to the Supraball server, so they work whichever launcher you use.
  Tick *Show all items* to browse and try on every skin and hat in the game. You can only wear
  items you own; clicking one you don't own opens its Steam Market page.
- **Game settings**: change resolution, window mode, FPS cap, graphics effects and mouse settings
  without starting the game. Close the game before saving, since it rewrites these files when it quits.
  Each save keeps a `.bak-` copy of the files it changes.
- **Settings**: makes this the launcher Steam's Play button opens, skips the official launcher's
  tutorial gate on a new install, and opens the official launcher for anything else.

## Run

```sh
uv run supraball-launcher        # or: uv run python -m supraball_launcher
```

Steam must be running. The Supraball install, Proton build and Steam Linux Runtime are detected
automatically; you can override them in *Settings*. Settings and presets are stored in
`~/.config/supraball-launcher/settings.json`.

## Use it as Supraball's launcher in Steam

1. Run `uv sync` once in this folder so `.venv/bin/supraball-launcher` exists.
2. In Steam, right-click Supraball, then go to *Properties > General > Launch Options* and enter:

   ```
   "/path/to/this/folder/steam-launch.sh" %command%
   ```

3. Press *Play*. This launcher opens in place of the official one. Steam shows you as in-game while it's open,
   and the game you start from it runs as part of the same session.

To go back to the official launcher, clear the launch options. If the `.venv` is missing,
`steam-launch.sh` starts the official launcher instead.

## Hosting notes

- Forward the **game port** (default 7777) and the **query port** (default 27015) over UDP for others to join.
- You can't host a public server from a network where you can't forward ports, such as a university,
  office or mobile connection. The master server answers `Invalid IP in ServerIP!` in the log when it
  can't use your address, and the Host tab shows this above the log. Use a private server over a LAN or VPN instead.
- *Check reachability* looks up your public address (from api.ipify.org) and compares it with this machine's.
  It can tell you're behind a router or carrier-grade NAT, but can't test your forwarded ports from outside.
- The game remembers the password and public IP in `UDKGame/Config/UDKDeathball.ini`. The launcher
  clears them before each start so a value from an earlier server doesn't carry over.
- *Private* servers use `?master=127.0.0.1`, so the "Failed to reach masterserver" lines in the log are expected.
- Server logs go to `UDKGame/Logs/sbl-server-<port>.log` inside the game folder.
- The *Copy* button gives you the raw `UDK.exe server …` command line, which you can use to run a server on another machine.

## How costumes work

Costumes are Steam Inventory items, and what you wear is stored on the Supraball master server.
The launcher signs in the way the official one does, using a Steam Encrypted App Ticket from
`tools/steamhelper/steamhelper.exe`, a small Windows helper run through Proton. The protocol is
documented in `docs/master-protocol.md`. Item artwork is extracted from your install's official
launcher into `~/.cache/supraball-launcher/art` the first time it's needed.

To rebuild the helper, install the 32-bit MinGW-w64 toolchain and run
`i686-w64-mingw32-gcc -O2 -s -o tools/steamhelper/steamhelper.exe tools/steamhelper/steamhelper.c`.

To re-learn the protocol after a game update, run `uv run python tools/capture_official.py`. It
records the official launcher's traffic into `captures/` (gitignored, since the files contain sign-in tickets).

## License

MIT, see `LICENSE`. The bundled fonts are under the SIL Open Font License (see `supraball_launcher/assets/fonts`).
