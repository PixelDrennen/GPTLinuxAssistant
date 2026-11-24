#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Usage: bash rider/build-local.sh /path/to/Rider\n' >&2
    exit 1
fi

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
sdk="$(realpath -- "$1")"
if [[ ! -d "$sdk/lib" ]] || ! compgen -G "$sdk/lib/*.jar" >/dev/null; then
    printf 'Choose the Rider installation folder that contains lib/.\n' >&2
    exit 1
fi

java_bin=""
if [[ -n "${JAVA_HOME:-}" ]]; then
    java_bin="$JAVA_HOME/bin/"
fi
build="$(mktemp -d)"
trap 'rm -rf -- "$build"' EXIT
mkdir -p "$build/classes" "$build/work-assistant-rider/lib" "$root/build/distributions"
"${java_bin}javac" --release 21 -encoding UTF-8 -classpath "$sdk/lib/*" -d "$build/classes" \
    "$root"/src/main/java/workassistant/*.java
cp -R -- "$root/src/main/resources/." "$build/classes/"
"${java_bin}jar" --create --file "$build/work-assistant-rider/lib/work-assistant-rider.jar" -C "$build/classes" .
output="$root/build/distributions/work-assistant-rider.zip"
"${java_bin}jar" --create --no-manifest --file "$output" -C "$build" work-assistant-rider
printf 'Install this ZIP from Rider Settings → Plugins → Install Plugin from Disk\n%s\n' "$output"
