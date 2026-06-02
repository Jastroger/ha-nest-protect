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

The product goal is zero DevTools setup: normal users should not open browser developer tools, export HAR files, inspect Network requests, search for Cookie headers, or run JavaScript snippets.

There is an important implementation constraint: a Home Assistant custom integration cannot read Google/Nest request headers from the user's browser. Browser security correctly prevents that. The config flow can accept an authentication helper output block, but the helper that captures Google browser traffic must run as an accessible companion app, browser extension, or Home Assistant add-on/Ingress app.

The config flow accepts a block shaped like this, using fake masked values:

```text
NEST_PROTECT_AUTH_WIZARD_OUTPUT_V1
issue_token=https://accounts.google.com/o/oauth2/iframerpc?action=issueToken&...
cookies=SID=***; HSID=***; SSID=***; APISID=***; SAPISID=***
END_NEST_PROTECT_AUTH_WIZARD_OUTPUT
```

The development script at `scripts/nest_protect_cookie_wizard.py` demonstrates the capture behavior, but it is not a finished normal-user setup experience because HACS users cannot access or run repository scripts from the Home Assistant config flow.

A true zero-DevTools user experience needs one of these implementation paths:

- Home Assistant add-on with browser/Ingress UI that runs the capture helper and returns the block.
- Small signed desktop companion app that opens a real browser and prints or copies the block.
- Browser extension with explicit permissions to capture the required request headers.

The pure Home Assistant config flow alone cannot capture the required Google request headers.

### Auth Bridge Callback Contract

The integration now has a callback endpoint for an add-on or companion app:

```text
POST /api/nest_protect/auth_bridge/{session_id}
```

Payload:

```json
{
  "secret": "one-time-session-secret",
  "issue_token": "https://accounts.google.com/o/oauth2/iframerpc?action=issueToken&...",
  "cookies": "SID=***; HSID=***; SSID=***; APISID=***; SAPISID=***"
}
```

The `session_id` and one-time secret are created by the Home Assistant config flow. The callback stores the result only when the secret matches. The config flow then validates the credentials and finishes setup.

### Manual Fallback / Troubleshooting Only

Use this only if no authentication helper is available. These values are specific to your Google account.

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
