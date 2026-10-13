#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DOCS_DIR="${ROOT_DIR}/docs"
RUBY_INSTALL_REPO="postmodern/ruby-install"
RUBY_INSTALL_API_URL="https://api.github.com/repos/${RUBY_INSTALL_REPO}/releases/latest"
LOCAL_PREFIX="${HOME}/.local"
LOCAL_BIN_DIR="${LOCAL_PREFIX}/bin"
GEM_USER_BIN=""
ADDED_GEM_USER_BIN=0
RUBY_BIN_DIR=""
ADDED_RUBY_BIN_DIR=0
ADDED_LOCAL_BIN_DIR=0
RUBY_INSTALL_BIN_DIR=""
ADDED_RUBY_INSTALL_BIN_DIR=0
UPDATED_SHELL_PROFILE=""

log() {
    printf '[docs-setup] %s\n' "$1"
}

fail() {
    printf '[docs-setup] %s\n' "$1" >&2
    exit 1
}

usage() {
  cat <<'EOF'
Usage: docs/scripts/setup_local_docs.sh [--skip-system-install]

Installs the local prerequisites for building the Jekyll documentation on
Linux or macOS, then installs the Ruby gems declared in docs/Gemfile.

By default this script bootstraps the latest ruby-install release into
$HOME/.local, then uses it to install and activate the latest stable Ruby.

Options:
  --skip-system-install  Skip ruby-install/Ruby installation and only prepare Bundler/gems.
  -h, --help             Show this help text.
EOF
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

ensure_local_bin_on_path() {
    if [[ ":${PATH}:" == *":${LOCAL_BIN_DIR}:"* ]]; then
        return
    fi
    
    export PATH="${LOCAL_BIN_DIR}:${PATH}"
    hash -r
    ADDED_LOCAL_BIN_DIR=1
}

detect_shell_profile() {
    local shell_name
    
    shell_name="$(basename "${SHELL:-}")"
    
    case "$shell_name" in
        zsh)
            printf '%s\n' "${HOME}/.zshrc"
        ;;
        bash)
            printf '%s\n' "${HOME}/.bashrc"
        ;;
        *)
            printf '%s\n' "${HOME}/.profile"
        ;;
    esac
}

persist_path_entry() {
    local path_dir="$1"
    local profile_path
    local export_line
    
    profile_path="$(detect_shell_profile)"
    export_line="export PATH=\"${path_dir}:\$PATH\""
    
    mkdir -p "$(dirname "$profile_path")"
    touch "$profile_path"
    
    if grep -Fqx "$export_line" "$profile_path"; then
        return
    fi
    
    printf '\n%s\n' "$export_line" >> "$profile_path"
    UPDATED_SHELL_PROFILE="$profile_path"
}

find_existing_ruby_install() {
    local candidate
    
    if command -v ruby-install >/dev/null 2>&1; then
        command -v ruby-install
        return 0
    fi
    
    for candidate in \
    "${LOCAL_BIN_DIR}/ruby-install" \
    "${HOME}/bin/ruby-install" \
    "/usr/local/bin/ruby-install" \
    "/opt/homebrew/bin/ruby-install" \
    "/home/linuxbrew/.linuxbrew/bin/ruby-install"
    do
        [[ -x "$candidate" ]] || continue
        printf '%s\n' "$candidate"
        return 0
    done
    
    return 1
}

ensure_ruby_install_on_path() {
    local ruby_install_path
    local bin_dir
    
    ruby_install_path="$(find_existing_ruby_install || true)"
    [[ -n "$ruby_install_path" ]] || return 1
    
    bin_dir="${ruby_install_path%/ruby-install}"
    RUBY_INSTALL_BIN_DIR="$bin_dir"
    
    if [[ ":${PATH}:" == *":${bin_dir}:"* ]]; then
        return 0
    fi
    
    export PATH="${bin_dir}:${PATH}"
    hash -r
    ADDED_RUBY_INSTALL_BIN_DIR=1
}

fetch_text() {
    local url="$1"
    
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url"
        return
    fi
    
    if command -v wget >/dev/null 2>&1; then
        wget -qO- "$url"
        return
    fi
    
    fail "Either curl or wget is required."
}

download_file() {
    local url="$1"
    local destination="$2"
    
    if command -v wget >/dev/null 2>&1; then
        wget -O "$destination" "$url"
        return
    fi
    
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$destination"
        return
    fi
    
    fail "Either curl or wget is required."
}

latest_ruby_install_version() {
    local version
    
    version="$(fetch_text "$RUBY_INSTALL_API_URL" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\{0,1\}\([^"]*\)".*/\1/p' | head -n 1)"
    [[ -n "$version" ]] || fail "Could not determine the latest ruby-install release."
    printf '%s\n' "$version"
}

current_ruby_install_version() {
    ensure_ruby_install_on_path || true
    
    if ! command -v ruby-install >/dev/null 2>&1; then
        return
    fi
    
    ruby-install --version 2>/dev/null | sed -E 's/[^0-9]*([0-9]+\.[0-9]+\.[0-9]+).*/\1/' | head -n 1
}

install_ruby_install_from_source() {
    local version="$1"
    local archive_name="ruby-install-${version}.tar.gz"
    local release_url="https://github.com/${RUBY_INSTALL_REPO}/releases/download/v${version}/${archive_name}"
    local work_dir
    local source_dir
    
    require_command tar
    require_command make
    
    work_dir="$(mktemp -d)"
    source_dir="${work_dir}/ruby-install-${version}"
    
    mkdir -p "$LOCAL_BIN_DIR"
    ensure_local_bin_on_path
    
    log "Downloading ruby-install ${version}"
    download_file "$release_url" "${work_dir}/${archive_name}"
    
    log "Installing ruby-install ${version} into ${LOCAL_PREFIX}"
    tar -xzf "${work_dir}/${archive_name}" -C "$work_dir"
    pushd "$source_dir" >/dev/null
    make PREFIX="$LOCAL_PREFIX" install
    popd >/dev/null
    
    rm -rf "$work_dir"
}

ensure_latest_ruby_install() {
    local latest_version
    local current_version
    
    ensure_ruby_install_on_path || true
    
    latest_version="$(latest_ruby_install_version)"
    current_version="$(current_ruby_install_version || true)"
    
    if [[ -n "$current_version" && "$current_version" == "$latest_version" ]]; then
        log "ruby-install ${current_version} is already installed"
        return
    fi
    
    install_ruby_install_from_source "$latest_version"
    command -v ruby-install >/dev/null 2>&1 || fail "ruby-install was installed but is not on PATH."
}

detect_latest_installed_ruby_bin() {
    local candidates=()
    local candidate
    local ruby_dir
    
    shopt -s nullglob
    for candidate in "${HOME}/.rubies"/ruby-* /opt/rubies/ruby-*; do
        [[ -d "$candidate/bin" ]] || continue
        candidates+=("$candidate")
    done
    shopt -u nullglob
    
    [[ "${#candidates[@]}" -gt 0 ]] || return 1
    
    ruby_dir="$(printf '%s\n' "${candidates[@]}" | sort -V | tail -n 1)"
    printf '%s/bin\n' "$ruby_dir"
}

activate_latest_installed_ruby() {
    local ruby_bin_dir
    
    ruby_bin_dir="$(detect_latest_installed_ruby_bin || true)"
    [[ -n "$ruby_bin_dir" ]] || return 1
    
    RUBY_BIN_DIR="$ruby_bin_dir"
    export PATH="${RUBY_BIN_DIR}:${PATH}"
    hash -r
    ADDED_RUBY_BIN_DIR=1
}

install_latest_ruby() {
    case "$(uname -s)" in
        Darwin|Linux)
        ;;
        *)
            fail "Unsupported operating system: $(uname -s)."
        ;;
    esac
    
    log "Installing the latest stable Ruby with ruby-install"
    ruby-install --update --rubies-dir "${HOME}/.rubies" ruby
    activate_latest_installed_ruby || fail "Could not locate the Ruby installed by ruby-install."
    persist_path_entry "$RUBY_BIN_DIR"
}

ensure_bundle() {
    if command -v bundle >/dev/null 2>&1; then
        return
    fi
    
    log "Installing Bundler into the user gem directory"
    gem install --user-install bundler
    
    GEM_USER_BIN="$(ruby -r rubygems -e 'print File.join(Gem.user_dir, "bin")')"
    export PATH="${GEM_USER_BIN}:${PATH}"
    hash -r
    ADDED_GEM_USER_BIN=1
    
    command -v bundle >/dev/null 2>&1 || fail "Bundler installation succeeded but bundle is still not on PATH."
}

install_docs_gems() {
    log "Installing documentation gems into docs/vendor/bundle"
    pushd "$DOCS_DIR" >/dev/null
    bundle config set --local path vendor/bundle
    bundle install
    popd >/dev/null
}

print_next_steps() {
    if [[ -n "$UPDATED_SHELL_PROFILE" ]]; then
        log "Updated ${UPDATED_SHELL_PROFILE} to include the installed Ruby on PATH."
    fi
    
    if [[ "$ADDED_RUBY_INSTALL_BIN_DIR" -eq 1 ]]; then
        log "Detected pre-installed ruby-install in ${RUBY_INSTALL_BIN_DIR}."
        log "Add it to your shell profile if you want it available in new shells:"
        printf 'export PATH="%s:$PATH"\n' "$RUBY_INSTALL_BIN_DIR"
    fi
    
    if [[ "$ADDED_LOCAL_BIN_DIR" -eq 1 ]]; then
        log "ruby-install was installed into ${LOCAL_PREFIX}."
        log "Add it to your shell profile if you want it available in new shells:"
        printf 'export PATH="%s:$PATH"\n' "$LOCAL_BIN_DIR"
    fi
    
    if [[ "$ADDED_RUBY_BIN_DIR" -eq 1 ]]; then
        log "Ruby was installed into ${RUBY_BIN_DIR%/bin}."
        log "Add it to your shell profile if you want this Ruby available in new shells:"
        printf 'export PATH="%s:$PATH"\n' "$RUBY_BIN_DIR"
    fi
    
    if [[ "$ADDED_GEM_USER_BIN" -eq 1 ]]; then
        log "Bundler was installed into ${GEM_USER_BIN}."
        log "Add it to your shell profile if you want bundle available in new shells:"
        printf 'export PATH="%s:$PATH"\n' "$GEM_USER_BIN"
    fi
    
    log "Setup complete. To build the docs locally:"
    log "  cd docs && bundle exec jekyll build --baseurl ''"
    log "To serve them locally with live reload:"
    log "  cd docs && bundle exec jekyll serve --livereload --baseurl ''"
}

main() {
    local skip_system_install=0
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-system-install)
                skip_system_install=1
            ;;
            -h|--help)
                usage
                exit 0
            ;;
            *)
                usage
                fail "Unknown argument: $1"
            ;;
        esac
        shift
    done
    
    if [[ ! -f "$DOCS_DIR/Gemfile" ]]; then
        fail "Could not find docs/Gemfile from ${DOCS_DIR}."
    fi
    
    ensure_local_bin_on_path
    
    if [[ "$skip_system_install" -eq 0 ]]; then
        ensure_latest_ruby_install
        install_latest_ruby
    else
        activate_latest_installed_ruby || true
    fi
    
    command -v ruby >/dev/null 2>&1 || fail "Ruby is not installed or not on PATH."
    command -v gem >/dev/null 2>&1 || fail "RubyGems is not installed or not on PATH."
    
    ensure_bundle
    install_docs_gems
    print_next_steps
}

main "$@"
