# Browser sign-in

The deployed frontend uses authorization code with S256 PKCE. It requests
`openid email profile`, consumes a one-time state/nonce transaction, exchanges
the code directly with the HTTPS token endpoint, and sends the access token to
the application API. No client secret belongs in a frontend build.

## Build configuration

Set all of these values before building:

- `VITE_API_BASE_URL`: API HTTPS origin, without `/api`.
- `VITE_OIDC_ISSUER`: exact user-pool issuer, such as
  `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_POOLID`.
- `VITE_OIDC_CLIENT_ID`: public app-client ID.
- `VITE_OIDC_AUTHORIZATION_ENDPOINT`: hosted-domain `/oauth2/authorize` URL.
- `VITE_OIDC_TOKEN_ENDPOINT`: hosted-domain `/oauth2/token` URL.
- `VITE_OIDC_LOGOUT_ENDPOINT`: hosted-domain `/logout` URL.

Issuer and endpoints must use HTTPS. Authorization, token, and logout endpoints
must share an origin. Missing or invalid partial configuration blocks private
API loads. Leaving all five OIDC values empty preserves explicit local fixtures.

The Cognito app client needs authorization-code flow, no client secret, and the
allowed scopes `openid`, `email`, and `profile`. Register the exact callback URL
`https://FRONTEND_ORIGIN/auth/callback` and sign-out URL
`https://FRONTEND_ORIGIN/`. The static host must serve the application at the
callback path. The API must allow that frontend origin in CORS and validate
Cognito access-token signatures, issuer, `token_use=access`, and the configured
`client_id` claim. Portal roles and client memberships remain server-controlled.

## Session behavior

Access and refresh tokens stay in memory. Session storage contains only the
temporary PKCE state, verifier, nonce, and transaction metadata, and is cleared
on callback or sign-out. Codes are removed from browser history before private
API calls. Claims parsed in the browser guard UI state; they do not replace
backend signature verification or authorization.

Refresh requests are shared by concurrent API calls and accept rotated refresh
tokens. Expired, revoked, or rejected sessions remove private UI state. A late
refresh cannot restore a signed-out session. After a full page reload, the user
signs in again; a valid hosted-login session can complete that redirect without
another password prompt.

Sign-out discards browser tokens and visits the hosted logout endpoint. It does
not claim immediate revocation of JWTs already issued to other holders or
sign-out from an external federated identity provider. Configure a short access
token lifetime and the required server-side revocation policy for the deployment.

No third-party fonts, analytics, or authentication SDK telemetry are loaded.
The content security policy needs the exact API and token endpoint origins in
`connect-src`; existing React inline styles require the corresponding style
policy. Authentication navigation occurs in the top-level browser.

## Checks

`npm run test`, `npm run typecheck`, `npm run lint`, `npm run build`, and
`npm run test:e2e` cover claim/state failures, memory-only tokens, refresh/logout
races, sign-in controls, ownership UI, and the fixed shell. Synthetic token tests
do not certify a live Cognito login; verify one after deploying the configured
user pool and provisioning the user's stable subject in the portal.

Provider behavior: [Cognito authorization](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html),
[token exchange and refresh](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html),
[managed-login logout](https://docs.aws.amazon.com/cognito/latest/developerguide/logout-endpoint.html).
