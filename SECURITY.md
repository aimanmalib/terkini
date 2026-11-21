# Security policy

## Reporting a vulnerability

Please use [private vulnerability reporting](https://github.com/aimanmalib/terkini/security/advisories/new). It reaches
only the maintainer. Don't open a public issue for a security problem.

Include what you found, how to reproduce it, and what an attacker could do with it. You will get a reply within seven
days.

## Supported versions

Only the latest release on the `main` branch gets fixes.

## What matters most here

- **Keys.** The Tavily key and the Bifrost virtual key are read from the environment and must never appear in logs,
  reports, recorded fixtures or the replay page. A path that leaks either one is a vulnerability.
- **The HTTP API.** `terkini serve` listens on `127.0.0.1` by default. In live mode it spends Tavily credits and model
  budget for every request, so it is not meant to face the internet without your own authentication in front of it.
- **Quotes.** A verdict needs a quote that appears in the official page text. A way to make Terkini mark a claim
  outdated or current without such a quote is in scope.
