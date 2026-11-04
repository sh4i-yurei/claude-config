REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"

setup_isolation() {
  mkdir -p "$BATS_TEST_TMPDIR/home" "$BATS_TEST_TMPDIR/vault"
}

# Every script start uses one explicit environment, including kcov's tracing state.
clean_env() {
  local path=$1
  shift
  local -a variables=("PATH=$path" "HOME=$BATS_TEST_TMPDIR/home")
  if [[ ${INCLUDE_SECOND_BRAIN:-1} == 1 ]]; then
    variables+=("SECOND_BRAIN=$BATS_TEST_TMPDIR/vault")
  fi
  local name
  for name in BASH_ENV BASH_XTRACEFD KCOV_BASH_COMMAND KCOV_BASH_XTRACEFD; do
    if [[ ${!name+x} ]]; then
      variables+=("$name=${!name}")
    fi
  done
  while [[ $# -gt 0 && $1 != -- ]]; do
    variables+=("$1")
    shift
  done
  shift
  env -i "${variables[@]}" "$@"
}

capture_case() {
  if clean_env "$@" >"$BATS_TEST_TMPDIR/stdout" 2>"$BATS_TEST_TMPDIR/stderr"; then
    CASE_STATUS=0
  else
    CASE_STATUS=$?
  fi
}

assert_text() {
  diff -u <(printf '%s' "$2") "$1"
}
