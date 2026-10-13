"""Place source files under this package so sbc-deploy's hermetic flake staging
(which only keeps files beneath the flake directory) ships them to Nix."""

def _flake_srcs_impl(ctx):
    outs = []
    for f in ctx.files.srcs:
        out = ctx.actions.declare_file(ctx.attr.prefix + "/" + f.short_path)
        ctx.actions.symlink(output = out, target_file = f)
        outs.append(out)
    return [DefaultInfo(files = depset(outs))]

flake_srcs = rule(
    implementation = _flake_srcs_impl,
    attrs = {
        "srcs": attr.label_list(allow_files = True, mandatory = True),
        "prefix": attr.string(mandatory = True, doc = "Subdirectory of this package to place files under."),
    },
    doc = "Re-roots files at <this package>/<prefix>/<workspace path>.",
)
