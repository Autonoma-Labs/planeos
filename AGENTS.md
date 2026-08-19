# Agent Development Guide

## Commands

- `pnpm dev` - Start all dev servers (web:3000, admin:3001)
- `pnpm build` - Build all packages and apps
- `pnpm check` - Run all checks (format, lint, types)
- `pnpm check:lint` - OxLint across all packages
- `pnpm check:types` - TypeScript type checking
- `pnpm fix` - Auto-fix format and lint issues
- `pnpm turbo run <command> --filter=<package>` - Target specific package/app
- `pnpm --filter=@plane/ui storybook` - Start Storybook on port 6006

## Code Style

- **Imports**: Use `workspace:*` for internal packages, `catalog:` for external deps
- **TypeScript**: Strict mode enabled, all files must be typed
- **Formatting**: oxfmt, run `pnpm fix:format`
- **Linting**: OxLint with shared `.oxlintrc.json` config
- **Naming**: camelCase for variables/functions, PascalCase for components/types
- **Error Handling**: Use try-catch with proper error types, log errors appropriately
- **State Management**: MobX stores in `packages/shared-state`, reactive patterns
- **Testing**: All features require unit tests, use existing test framework per package
- **Components**: Build in `@plane/ui` with Storybook for isolated development

## Backend tests (Docker)

The Django/pytest suite for `apps/api` runs in an isolated stack defined by `docker-compose-test.yml` at the repo root.

Prereq (once): `./setup.sh` — generates `apps/api/.env` from `.env.example`.

- Full suite: `docker compose -f docker-compose-test.yml up --build --abort-on-container-exit --exit-code-from api-tests`
- Subset: `docker compose -f docker-compose-test.yml run --rm api-tests pytest -m unit`
- Teardown: `docker compose -f docker-compose-test.yml down -v`

See `apps/api/tests/RUNNING_TESTS.md` for the full walkthrough and troubleshooting; see `apps/api/tests/TESTING_GUIDE.md` for test conventions and fixtures.

## Autonoma test data

Autonoma generates and runs end-to-end tests against a preview deployment of this
repo. Before each run it seeds an isolated workspace by calling one signed endpoint,
`POST /api/autonoma` (`plane/autonoma/`), whose factories build the data through the
app's own creation code — the real serializers, view logic and model `save()`
overrides — so the seeded rows carry the same defaults, hashed passwords, derived
columns and side effects a real user's would. Teardown deletes the seeded workspace
and its users, which removes everything scoped to them.

When you add or change a model, or change the code that creates one, add or update
the matching factory in `plane/autonoma/factories/` and register it in
`plane/autonoma/factories/__init__.py`. Two rules matter: call the app's real
creation path rather than writing rows directly, and take an offset (`starts_in_days`,
`expires_in_days`, …) instead of a fixed date for any column the app compares against
the current time — the recipe is stored once and replayed for months.
