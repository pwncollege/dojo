_final: prev: {
  sage = prev.sage.override {
    extraPythonPackages =
      ps: with ps; [
        pycryptodome
        pwntools
      ];
    requireSageTests = false;
  };
}
