#!/usr/bin/env bats
load helper

setup() {
  setup_isolation
  script_path="$REPO_ROOT/tools/vault-env"
  marker="$BATS_TEST_TMPDIR/bw-ran"
  mkdir -p "$BATS_TEST_TMPDIR/bin"
  printf '#!/bin/sh\nprintf ran > "$BW_MARKER"\n' >"$BATS_TEST_TMPDIR/bin/bw"
  chmod +x "$BATS_TEST_TMPDIR/bin/bw"
  path="$BATS_TEST_TMPDIR/bin:/usr/bin:/bin"
}

@test "arguments refuse vault access" {
  local argument
  for argument in --help -h GH_TOKEN; do
    capture_case "$path" "BW_MARKER=$marker" -- "$script_path" "$argument"
    [ "$CASE_STATUS" -eq 2 ]
    [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
    assert_text "$BATS_TEST_TMPDIR/stderr" 'usage: eval "$(vault-env)"'$'\n'
    [ ! -e "$marker" ]
  done
}

@test "terminal stdout refuses vault access without output" {
  capture_case "$path" "BW_MARKER=$marker" -- script -qec "$script_path 2>$BATS_TEST_TMPDIR/terminal-stderr" /dev/null
  [ "$CASE_STATUS" -eq 2 ]
  [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
  [ ! -s "$BATS_TEST_TMPDIR/stderr" ]
  assert_text "$BATS_TEST_TMPDIR/terminal-stderr" 'usage: eval "$(vault-env)"'$'\n'
  [ ! -e "$marker" ]
}

@test "outside container refuses vault access" {
  if [ -f /run/.containerenv ]; then
    local -a command=(flatpak-spawn --host --clear-env "--env=PATH=$path" "--env=HOME=$BATS_TEST_TMPDIR/home" "--env=BW_MARKER=$marker" "$script_path")
    local bus_address="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"
    capture_case "$path" "BW_MARKER=$marker" "DBUS_SESSION_BUS_ADDRESS=$bus_address" -- "${command[@]}"
  else
    capture_case "$path" "BW_MARKER=$marker" -- "$script_path"
  fi
  [ "$CASE_STATUS" -eq 1 ]
  [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
  assert_text "$BATS_TEST_TMPDIR/stderr" 'vault-env: bw runs only inside the dev container (distrobox enter dev)'$'\n'
  [ ! -e "$marker" ]
}
