# Nest Protect for Home Assistant

This custom integration exposes Google Nest Protect smoke and CO detectors in Home Assistant.

It uses the unofficial Nest web API because Nest Protect is not exposed through the official Google Nest Device Access / SDM API. A Nest Protect can appear in the Google Home app and still not be available through the official Home Assistant Nest integration.

## Supported Devices

- Nest Protect smoke and CO alarms
- Wired Nest Protect occupancy, where available
- Configuration entities such as Pathlight, Nightly Promise, Heads-Up, Steam Check, and night light brightness

## Known Limitations

- Only Google accounts are supported.
- Nest Protect support depends on an unofficial Nest web authentication flow.
- If you log out of `home.nest.com`, change your password, or Google invalidates your browser session, you may need to reauthenticate.
- Wired occupancy can remain on for about 10 minutes because of the Nest behavior.
- Google can change the web flow without notice.

## Installation

### HACS

1. Open HACS.
2. Search for `Nest Protect`.
3. Install the integration.
4. Restart Home Assistant.
5. Add the integration from Settings > Devices & services.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=nest_protect)

### Manual

1. Copy `custom_components/nest_protect` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from Settings > Devices & services.

## Zero DevTools Setup

The normal setup path is the Playwright auth wizard. Normal users should not open browser developer tools, export HAR files, inspect Network requests, search for Cookie headers, or run JavaScript snippets.

The wizard opens a real browser, lets you sign in to Google normally, listens to local browser network traffic, and captures the two values Home Assistant needs:

- Issue Token URL
- Cookie header from the `oauth2/iframe` Network request

The wizard does not use `document.cookie`, because that usually misses required Google authentication cookies. It does not read your Google password; login happens inside the browser window.

### Run The Wizard

From this repository:

```bash
python -m pip install playwright
python -m playwright install chromium
python scripts/nest_protect_cookie_wizard.py
```

For an extra end-to-end check before printing the final block:

```bash
python scripts/nest_protect_cookie_wizard.py --validate
```

Optional browser choices:

```bash
python scripts/nest_protect_cookie_wizard.py --browser chromium
python scripts/nest_protect_cookie_wizard.py --browser chrome
python scripts/nest_protect_cookie_wizard.py --browser edge
```

Complete login in the browser window. When both values are captured, paste the combined block into the first field of the Home Assistant setup form.

Do not log out of `home.nest.com` after capturing the values.

Example block shape with fake values:

```text
NEST_PROTECT_AUTH_WIZARD_OUTPUT_V1
issue_token=https://accounts.google.com/o/oauth2/iframerpc?action=issueToken&...
cookies=SID=***; HSID=***; SSID=***; APISID=***; SAPISID=***
END_NEST_PROTECT_AUTH_WIZARD_OUTPUT
```

### Manual Fallback / Troubleshooting Only

Use this only if the wizard cannot run or troubleshooting needs to prove what the browser is sending. This is not the normal setup path.

1. Open a private or incognito browser window.
2. Open Developer Tools and go to the Network tab.
3. Enable Preserve log.
4. Go to `https://home.nest.com`.
5. Sign in with Google.
6. Filter for `issueToken`.
7. Copy the full request URL beginning with `https://accounts.google.com/o/oauth2/iframerpc`.
8. Filter for `oauth2/iframe`.
9. Open the latest matching request.
10. Copy the full Cookie request header.
11. Paste both values into Home Assistant.

Important: copy the Cookie request header from the Network request. Do not copy `document.cookie`.

## Reauthentication

If Home Assistant reports that Nest Protect authentication expired:

1. Run the wizard again.
2. Paste the new values into the reauthentication flow.
3. Keep the browser session valid by closing the window instead of logging out.

## Troubleshooting

### Invalid Issue Token URL

Run the wizard again and paste the complete wizard block. If using the emergency fallback, paste the complete `issueToken` request URL, including query parameters. It should begin with:

```text
https://accounts.google.com/o/oauth2/iframerpc
```

### Incomplete Cookie Header

Run the wizard again and wait until the Nest web app fully loads. If using the emergency fallback, copy the full Cookie request header from the `oauth2/iframe` Network request. It should contain several Google cookie names such as `SID`, `HSID`, `SSID`, `APISID`, or `SAPISID`.

### Wizard Sees oauth2 iframe But No Issue Token

Keep the browser open, reload `https://home.nest.com`, and wait until the Nest web app fully loads. If it still does not capture an Issue Token URL, retry in a fresh browser context and confirm that your Google account migration is complete.

### Google/Nest Authentication Rejected

Run the wizard again in a fresh browser context. Do not log out after copying the credentials.

### No Nest Protect Devices Found

The Google account authenticated successfully, but the Nest web response did not include supported Nest Protect devices. Confirm that the same account can see the devices at `home.nest.com`.

### Network Timeout

Retry after checking network connectivity and DNS. Google/Nest endpoints can also be temporarily slow or unavailable.

## Security Notes

Treat the Issue Token URL, Cookie header, access tokens, refresh tokens, and JWTs like passwords.

This repository must not contain real tokens or cookies. Diagnostics redact known secret fields. If you share logs or diagnostics, review them first.

The wizard prints captured credentials because you need to paste them into Home Assistant. It masks values in status and debug output by default and does not write credential files. `--show-secrets` is intentionally unsafe and should only be used for local troubleshooting.

## Development

The current test dependency pin is intentionally conservative:

```text
homeassistant==2024.12.1
```

This version already requires a modern Python runtime. On Windows, some native Home Assistant dependencies may require Microsoft C++ Build Tools if prebuilt wheels are not available for your Python version.

Recommended commands:

```bash
python -m pip install -r requirements_test.txt
python -m pytest
python -m compileall -q custom_components tests
```

No tests should call Google or Nest directly. Network access must be mocked.

## Contributing

Please keep changes focused and avoid speculative rewrites. In particular, do not replace this integration with the official SDM API unless Nest Protect support is proven by official documentation and working code.

Useful issue reports include:

- Home Assistant version
- Integration version or commit
- Redacted diagnostics
- Relevant log excerpts with tokens and cookies removed

## Credits

Based on research and implementation ideas from the Nest and Homebridge communities, especially `homebridge-nest`.
