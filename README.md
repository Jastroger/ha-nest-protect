![Detail page of a Nest Protect device](https://github.com/iMicknl/ha-nest-protect/assets/1424596/8fd15c57-2a9c-4c20-8c8f-65a526573d1e)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/Jastroger/ha-nest-protect.svg)](https://GitHub.com/Jastroger/ha-nest-protect/releases/)
[![HA integration usage](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.nest_protect.total)](https://analytics.home-assistant.io/custom_integrations.json)

# Nest Protect integration for Home Assistant

Custom component for Home Assistant to interact with Nest Protect devices via an undocumented and unofficial Nest API. Unfortunately, Google SDM doesn't support Nest Protect devices and thus the core [Nest integration](https://www.home-assistant.io/integrations/nest/) won't work for Nest Protect.

This integration will add the most important sensors of your Nest Protect device (CO, heat and smoke) and the occupancy if your device is wired (to main power). In addition, it will expose several diagnostic and configuration entities. All sensor values will be updated real-time.

## Known limitations

- Only Google Accounts are supported, there is no plan to support legacy Nest accounts
- When Nest Protect (wired) occupancy is triggered, it will stay 'on' for 10 minutes. (API limitation)
- Only _cookie authentication_ is supported as Google removed the API key authentication method. This means that you need to login to the Nest website at least once to generate a cookie. This cookie will be used to authenticate with the Nest API. The cookie will be stored in the Home Assistant configuration folder and will be used for future requests. If you logout from your browser or change your password, you need to reautenticate and and replace the current issue_token and cookies.

## Installation

You can install this integration via [HACS](#hacs) or [manually](#manual).

### HACS

Add this repository (`https://github.com/Jastroger/ha-nest-protect`) as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/) in HACS with the category **Integration**. Then search for the Nest Protect integration and choose install, then reboot Home Assistant. Configure the Nest Protect integration either via the integrations page or press the blue button below.


[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=nest_protect)

### Manual

Copy the `custom_components/nest_protect` to your custom_components folder and reboot Home Assistant. Configure the Nest Protect integration either via the integrations page or press the blue button below.


[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=nest_protect)

## Authentication Setup

Primary path for Home Assistant OS / Supervised:

1. Install this integration.
1. Install the **Nest Protect Auth Bridge** add-on.
1. Add the Nest Protect integration in Home Assistant.
1. Start login in the integration flow.
1. Click the launch link to open the add-on Ingress page with one-time session parameters.
1. Complete Google/Nest sign-in in the visible browser embedded in the Auth Bridge add-on UI.
1. Return to Home Assistant and click **Submit** / **Continue after login** if needed.
1. Setup completes automatically once callback validation succeeds.

Alternative path for Home Assistant Container / Core:

1. Install this integration.
1. Start the **Nest Protect Auth Bridge** as a standalone Docker container.
1. Add the Nest Protect integration in Home Assistant.
1. Start login in the integration flow.
1. Open the standalone Auth Bridge web UI, for example `http://<docker-host>:8099`.
1. Complete Google/Nest sign-in in the visible browser embedded in the Auth Bridge UI.
1. Return to Home Assistant and click **Submit** / **Continue after login** if needed.
1. Setup completes automatically once callback validation succeeds.

The product goal is zero DevTools setup: normal users should not open browser developer tools, export HAR files, inspect Network requests, search for Cookie headers, or run JavaScript snippets.

### Standalone Docker Auth Bridge

Use standalone mode when you run Home Assistant Container or Core and cannot install Home Assistant add-ons.

Copy `docker-compose.example.yml`, then set `HA_BASE_URL` to the URL that the Auth Bridge container can use to reach Home Assistant:

```bash
HA_BASE_URL=http://homeassistant.local:8123
AUTH_BRIDGE_PORT=8099
docker compose -f docker-compose.example.yml up
```

Standalone mode uses the same browser capture UI as the add-on, but posts the callback directly to:

```text
http://<ha-host>:8123/api/nest_protect/auth_bridge/{session_id}
```

It does not require the Home Assistant Add-on Store and does not use `SUPERVISOR_TOKEN`.

### Auth Bridge add-on runtime / developer notes

Use these notes for release validation and troubleshooting.

1. Install this repository's add-on source as a **local add-on** (copy `addons/nest-protect-auth-bridge` into your Home Assistant local add-ons directory).
1. In Home Assistant, go to **Settings → Add-ons**, open **Nest Protect Auth Bridge**, then click **Start**.
1. Open the add-on through the Home Assistant sidebar (Ingress panel: **Nest Protect Auth Bridge**). The config-flow launch link should also open this Ingress page with one-time launch parameters.
1. Click **Start Login** and confirm noVNC shows a live Chromium window (Nest sign-in page rendered inside the embedded browser frame).
1. If something fails, check logs in both places:
   - Home Assistant add-on log panel (**Settings → Add-ons → Nest Protect Auth Bridge → Log**)
   - Runtime files inside the add-on container: `/tmp/auth-bridge.log` (Flask/Playwright/Chromium), `/tmp/websockify.log`, `/tmp/x11vnc.log`, `/tmp/fluxbox.log`
1. Known limitation: Home Assistant Ingress URL handling can vary by installation/frontend path. The config-flow launch link behavior must be tested on real HA OS/Supervised environments before release.
1. Manual wizard/DevTools flow remains fallback-only for troubleshooting and should not be the default user path.

### Auth Bridge Callback Contract

The integration now has a callback endpoint for an add-on or companion app:

```text
POST http://supervisor/core/api/nest_protect/auth_bridge/{session_id}
```

For standalone Docker mode, use the Home Assistant base URL instead:

```text
POST http://<ha-host>:8123/api/nest_protect/auth_bridge/{session_id}
```

Payload:

```json
{
  "secret": "one-time-session-secret",
  "issue_token": "https://accounts.google.com/o/oauth2/iframerpc?action=issueToken&...",
  "cookies": "SID=***; HSID=***; SSID=***; APISID=***; SAPISID=***"
}
```

The `session_id` and one-time secret are created by the Home Assistant config flow. Add-ons should call the Supervisor/Core API callback with the Supervisor token. Standalone Docker mode should call the Home Assistant callback URL directly and relies on the one-time secret for protection. The callback stores the result only when the secret matches. The config flow then validates the credentials and finishes setup.

### Manual Fallback / Troubleshooting Only

Use this only if the Auth Bridge add-on / companion flow is unavailable. These values are specific to your Google account.

1. Open a Chrome/Edge browser tab in Incognito Mode.
1. Allow third-party cookies in your browser settings to prevent the Nest website from entering a redirect loop. Follow these steps:

   - **In Chrome**: Go to Settings, select Privacy and Security -> Third-party cookies. Enable "Allow third-party cookies."
   - **In Edge**: Go to Settings, select Cookies and site permissions -> Manage and delete cookies and site data. Disable "Block third-party cookies."

1. Open Developer Tools.
1. Click on **Network** tab. Make sure 'Preserve Log' is checked.
1. In the **Filter** box, enter `issueToken`
1. Go to home.nest.com, and click **Sign in with Google**. Log into your account.
1. One network call (beginning with iframerpc) will appear in the Dev Tools window. Click on it.
1. In the Headers tab, under General, copy the entire Request URL (beginning with https://accounts.google.com). This is your _'issue_token'_ in the configuration form.
1. In the **Filter** box, enter `oauth2/iframe`
1. Several network calls will appear in the Dev Tools window. Click on the last iframe call.
1. In the **Headers** tab, under **Request Headers**, copy the entire cookie (include the whole string which is several lines long and has many field/value pairs - do not include the cookie: name). This is your _'cookies'_ in the configuration form.
1. Do not log out of home.nest.com, as this will invalidate your credentials. Just close the browser tab.

## Advanced

Feel free to [create an issue on GitHub](https://github.com/Jastroger/ha-nest-protect/issues/new/choose) if you find an issue or if you have a suggestion. It is always helpful to download the diagnostics information and to include debug logging.

### Enable debug logging

The [logger](https://www.home-assistant.io/integrations/logger/) integration lets you define the level of logging activities in Home Assistant. Turning on debug mode will show more information about unsupported devices in your logbook.

```
logger:
  default: critical
  logs:
    custom_components.nest_protect: debug
```

## Credits

Based on the research and implementation of [homebridge-nest](https://github.com/chrisjshull/homebridge-nest).
