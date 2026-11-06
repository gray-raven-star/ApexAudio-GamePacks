# ApexAudio GamePacks

Official game adaptation packages for ApexAudio.

## Download

Find the current version and release history for each game on the [official download page](https://gray-raven-star.github.io/ApexAudio-GamePacks/).

## Releases

Each package version has a [GitHub Release](https://github.com/gray-raven-star/ApexAudio-GamePacks/releases) tagged `pack/<slug>/v<version>` with a `.gpack` and its `.sha256` checksum. [`registry.json`](registry.json) is the machine-readable index used to generate the download page.

## Publish a package

Run **Publish game pack** from the Actions tab on the distribution repository's `main` branch. Supply the lowercase package directory name as `slug`, the manifest version in `MAJOR.MINOR.PATCH` format as `version`, and an ApexAudio source ref as `source_ref`. The source ref defaults to `main`. Use a commit SHA to pin the source across retries.

The [ApexAudio source repository](https://github.com/gray-raven-star/ApexAudio) must have a buildable `gamepacks/<slug>/` definition at that ref, with `manifest.version` matching the requested version. The workflow uses .NET 8 and Zig 0.15.2 to build the package, runs the offline DevTools package check, then publishes the Release, updates the registry, and deploys the download page.

If the Release succeeded and the index or page update failed, rerun with the same package, version, and source commit. The workflow builds again, checks the published assets against their checksum, and refreshes the index and page from those assets.

## Community Packages

The registry and release workflow cover official ApexAudio packages. Community packages are distributed separately.
