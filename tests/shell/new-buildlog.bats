#!/usr/bin/env bats
load helper

setup() {
  setup_isolation
  script_path="$REPO_ROOT/skills/buildlog/scripts/new-buildlog.sh"
  vault="$BATS_TEST_TMPDIR/vault"
  mkdir -p "$vault/_Templates"
  cp "$BATS_TEST_DIRNAME/fixtures/buildlog-log.md" "$vault/_Templates/buildlog-log.md"
}

@test "missing slug prints usage without creating logs" {
  capture_case /usr/bin:/bin -- "$script_path"
  [ "$CASE_STATUS" -eq 2 ]
  [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
  assert_text "$BATS_TEST_TMPDIR/stderr" 'usage: new-buildlog.sh <slug> [project-note-name]'$'\n'
  [ ! -e "$vault/20_Buildlogs" ]
}

@test "invalid slugs are refused without creating logs" {
  local slug
  for slug in Bad_Slug trailing- two--hyphens; do
    capture_case /usr/bin:/bin -- "$script_path" "$slug"
    [ "$CASE_STATUS" -eq 2 ]
    [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
    assert_text "$BATS_TEST_TMPDIR/stderr" "error: slug must be lowercase words separated by hyphens (got '$slug')"$'\n'
    [ ! -e "$vault/20_Buildlogs" ]
  done
}

@test "missing template is refused without creating logs" {
  rm "$vault/_Templates/buildlog-log.md"
  capture_case /usr/bin:/bin -- "$script_path" shell-ci-test
  [ "$CASE_STATUS" -eq 1 ]
  [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
  assert_text "$BATS_TEST_TMPDIR/stderr" "error: missing template $vault/_Templates/buildlog-log.md"$'\n'
  [ ! -e "$vault/20_Buildlogs" ]
}

@test "existing buildlog is preserved" {
  local dir="$vault/20_Buildlogs/shell-ci-test"
  mkdir -p "$dir"
  printf 'keep this exactly\n' >"$dir/existing.md"
  cp "$dir/existing.md" "$BATS_TEST_TMPDIR/original"
  capture_case /usr/bin:/bin -- "$script_path" shell-ci-test
  [ "$CASE_STATUS" -eq 1 ]
  [ ! -s "$BATS_TEST_TMPDIR/stdout" ]
  assert_text "$BATS_TEST_TMPDIR/stderr" "error: $dir already exists — append to it instead of scaffolding over it"$'\n'
  cmp -s "$dir/existing.md" "$BATS_TEST_TMPDIR/original"
}

@test "project buildlog matches the template substitutions and output" {
  local dir="$vault/20_Buildlogs/shell-ci-test"
  capture_case /usr/bin:/bin -- "$script_path" shell-ci-test 'Nightly issue pipeline'
  [ "$CASE_STATUS" -eq 0 ]
  [ ! -s "$BATS_TEST_TMPDIR/stderr" ]
  [ -d "$dir/images" ]
  local today
  today="$(TZ=America/Chicago date '+%Y-%m-%d')"
  sed -e "s|<% tp.date.now(\"YYYY-MM-DD\") %>|$today|g" -e 's|^project: "\[\[\]\]"|project: "[[Nightly issue pipeline]]"|' "$BATS_TEST_DIRNAME/fixtures/buildlog-log.md" >"$BATS_TEST_TMPDIR/expected"
  cmp -s "$dir/shell-ci-test-log.md" "$BATS_TEST_TMPDIR/expected"
  assert_text "$BATS_TEST_TMPDIR/stdout" "created:
  $dir/shell-ci-test-log.md
  $dir/images/
linked to project: [[Nightly issue pipeline]]"$'\n'
}

@test "no project leaves the template link and prints its note" {
  local dir="$vault/20_Buildlogs/shell-ci-test"
  capture_case /usr/bin:/bin -- "$script_path" shell-ci-test
  [ "$CASE_STATUS" -eq 0 ]
  [ ! -s "$BATS_TEST_TMPDIR/stderr" ]
  [ -d "$dir/images" ]
  local today
  today="$(TZ=America/Chicago date '+%Y-%m-%d')"
  sed -e "s|<% tp.date.now(\"YYYY-MM-DD\") %>|$today|g" "$BATS_TEST_DIRNAME/fixtures/buildlog-log.md" >"$BATS_TEST_TMPDIR/expected"
  cmp -s "$dir/shell-ci-test-log.md" "$BATS_TEST_TMPDIR/expected"
  assert_text "$BATS_TEST_TMPDIR/stdout" "created:
  $dir/shell-ci-test-log.md
  $dir/images/
note: no project given — set 'project:' in the log frontmatter"$'\n'
}

@test "HOME supplies the vault when SECOND_BRAIN is absent" {
  local home_vault="$BATS_TEST_TMPDIR/home/Documents/Second_Brain"
  mkdir -p "$home_vault/_Templates"
  cp "$BATS_TEST_DIRNAME/fixtures/buildlog-log.md" "$home_vault/_Templates/buildlog-log.md"
  INCLUDE_SECOND_BRAIN=0 capture_case /usr/bin:/bin -- "$script_path" shell-ci-test
  [ "$CASE_STATUS" -eq 0 ]
  [ -f "$home_vault/20_Buildlogs/shell-ci-test/shell-ci-test-log.md" ]
}
