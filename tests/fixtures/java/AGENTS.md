# Java Hexagonal Lambda Service

## Build

- Build with **Maven** (multi-module).
- JPMS: every module declares a `module-info.java`.

## Architecture

- Hexagonal architecture (ports and adapters) with `domain`, `application` and `infrastructure` modules.
- Dependency injection with Guice.
- Infrastructure is provisioned with Terraform.

## Security

- No secrets in source.
- Every endpoint is authenticated by default using OAuth.

## Testing

- Component tests are written in Gherkin.
- Never skip tests.

## Quality

- Checkstyle and SpotBugs run in the Maven build.

## Specs

- Specs live in `specs/` (spec-first).
- Architecture decisions are recorded as ADRs.

## Layout

```
├── pom.xml
├── domain/
│   └── src/main/java/module-info.java
├── application/
├── infrastructure/
└── terraform/
```
