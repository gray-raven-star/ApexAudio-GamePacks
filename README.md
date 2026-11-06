# ApexAudio GamePacks

Official game adaptation packages for ApexAudio.

## Download

<!-- BEGIN GENERATED DOWNLOADS -->

No official packs have been published here yet.

<!-- END GENERATED DOWNLOADS -->

## Releases

Each package version has a [GitHub Release](https://github.com/gray-raven-star/ApexAudio-GamePacks/releases) tagged `pack/<slug>/v<version>` with a `.gpack` and its `.sha256` checksum. The download list above is generated from the machine-readable [`registry.json`](registry.json).

## Publish a package

Run **Publish game pack** from the Actions tab on the distribution repository's `main` branch. Supply the lowercase package directory name as `slug`, the manifest version in `MAJOR.MINOR.PATCH` format as `version`, and an ApexAudio source ref as `source_ref`. The source ref defaults to `main`. Use a commit SHA to pin the source across retries.

The [ApexAudio source repository](https://github.com/gray-raven-star/ApexAudio) must have a buildable `gamepacks/<slug>/` definition at that ref, with `manifest.version` matching the requested version. The workflow uses .NET 8 and Zig 0.15.2 to build the package, runs the offline DevTools package check, and publishes the Release. It then commits the registry and generated download list together. Pull request checks verify that the list matches the registry.

If the Release succeeded and the index update failed, rerun with the same package, version, and source commit. The workflow builds again, checks the published assets against their checksum, and refreshes the index from those assets.

## Community Packages

The registry and release workflow cover official ApexAudio packages. Community packages are distributed separately.
