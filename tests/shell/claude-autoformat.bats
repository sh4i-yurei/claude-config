#!/usr/bin/env bats
load helper

setup() {
  setup_isolation
  script_path="$REPO_ROOT/hooks/claude-autoformat.sh"
  bin="$BATS_TEST_TMPDIR/bin"
  record="$BATS_TEST_TMPDIR/formats"
  mkdir -p "$bin"
  ln -s "$(command -v jq)" "$bin/jq"
  ln -s "$(command -v cat)" "$bin/cat"
  local formatter
  for formatter in ruff rustfmt gofmt; do
    cat >"$bin/$formatter" <<'EOF'
#!/bin/bash
if [[ ${RUFF_FAIL:-0} == 1 && $0 == */ruff ]]; then
  echo 'ruff failed' >&2
  exit 1
fi
printf '%s\n' "${0##*/}" "$@" >>"$FORMAT_RECORD"
EOF
    chmod +x "$bin/$formatter"
  done
}

write_event() {
  jq --arg path "$1" '.tool_input.file_path=$path | .tool_response.filePath=$path' "$BATS_TEST_DIRNAME/fixtures/write.json" >"$BATS_TEST_TMPDIR/event"
}

format_case() {
  capture_case "$bin" "FORMAT_RECORD=$record" -- "$script_path" <"$BATS_TEST_TMPDIR/event"
  [ "$CASE_STATUS" -eq 0 ]
  [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
  [ ! -s "$BATS_TEST_TMPDIR/stderr" ]
}

@test "Write events call only the formatter for each supported extension" {
  local extension expected file
  for extension in py rs go; do
    file="$BATS_TEST_TMPDIR/example.$extension"
    : >"$file"
    write_event "$file"
    format_case
    case "$extension" in
      py) expected="ruff"$'\n'"format"$'\n'"--quiet"$'\n'"$file"$'\n' ;;
      rs) expected="rustfmt"$'\n'"--edition"$'\n'"2021"$'\n'"$file"$'\n' ;;
      go) expected="gofmt"$'\n'"-w"$'\n'"$file"$'\n' ;;
    esac
    assert_text "$record" "$expected"
    rm "$record"
  done
}

@test "unsupported, missing, and Bash event paths run no formatter" {
  local file="$BATS_TEST_TMPDIR/example.md"
  : >"$file"
  write_event "$file"
  format_case
  [ ! -e "$record" ]

  write_event "$BATS_TEST_TMPDIR/missing.py"
  format_case
  [ ! -e "$record" ]

  cp "$BATS_TEST_DIRNAME/fixtures/bash.json" "$BATS_TEST_TMPDIR/event"
  format_case
  [ ! -e "$record" ]
}

@test "missing ruff leaves the file unchanged" {
  local file="$BATS_TEST_TMPDIR/example.py"
  printf 'original bytes\n' >"$file"
  cp "$file" "$BATS_TEST_TMPDIR/original"
  write_event "$file"
  rm "$bin/ruff"
  format_case
  cmp -s "$file" "$BATS_TEST_TMPDIR/original"
  [ ! -e "$record" ]
}

@test "ruff failure is silent and does not fail the hook" {
  local file="$BATS_TEST_TMPDIR/example.py"
  : >"$file"
  write_event "$file"
  capture_case "$bin" "FORMAT_RECORD=$record" "RUFF_FAIL=1" -- "$script_path" <"$BATS_TEST_TMPDIR/event"
  [ "$CASE_STATUS" -eq 0 ]
  [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
  [ ! -s "$BATS_TEST_TMPDIR/stderr" ]
  [ ! -e "$record" ]
}
