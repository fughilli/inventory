# The three deployables, built from the Bazel-staged sources in ./src.
{ python3Packages, buildNpmPackage, importNpmLock }:
let
  src = ./src;
in
{
  # FastAPI server + SQLite + CLIP embeddings. Its unit tests run in checkPhase.
  server = python3Packages.buildPythonApplication {
    pname = "inventory";
    version = "0.1.0";
    pyproject = true;
    src = src + "/server";
    build-system = [ python3Packages.setuptools ];
    dependencies = with python3Packages; [
      fastapi
      uvicorn
      python-multipart
      httpx
      pillow
      qrcode
      numpy
      onnxruntime
      tokenizers
      anthropic
    ];
    nativeCheckInputs = [ python3Packages.pytestCheckHook ];
  };

  # TSPL print agent for the USB label printer.
  printd = python3Packages.buildPythonApplication {
    pname = "printd";
    version = "0.1.0";
    pyproject = true;
    src = src + "/printd";
    build-system = [ python3Packages.setuptools ];
    dependencies = [ python3Packages.pillow ];
    nativeCheckInputs = [ python3Packages.pytestCheckHook ];
  };

  # The PWA, built with vite. importNpmLock reads package-lock.json directly,
  # so there is no npmDepsHash to keep updated.
  web = buildNpmPackage {
    pname = "inventory-web";
    version = "0.1.0";
    src = src + "/web";
    npmDeps = importNpmLock { npmRoot = src + "/web"; };
    npmConfigHook = importNpmLock.npmConfigHook;
    installPhase = ''
      runHook preInstall
      cp -r dist $out
      runHook postInstall
    '';
  };
}
