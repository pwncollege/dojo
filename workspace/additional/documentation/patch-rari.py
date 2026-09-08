from pathlib import Path


path = Path("crates/rari-deps/src/npm.rs")
source = path.read_text()
start = source.index("    let package_path = out_path.join(package);", source.index("pub fn get_package("))
end = source.index("\n}\n", start)
source = source[:start] + "    Ok(Some(out_path.join(package)))" + source[end:]
path.write_text(source)

path = Path("crates/rari-cli/main.rs")
source = path.read_text()
for dependency in ("developer_signals", "web_ext_examples", "popularities"):
    line = f"        rari_deps::{dependency}::update_{dependency}(rari_types::globals::data_dir())?;\n"
    assert line in source, dependency
    source = source.replace(line, "")
path.write_text(source)
