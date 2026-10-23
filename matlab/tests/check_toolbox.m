function check_toolbox(toolbox, example)
%CHECK_TOOLBOX Installs a packaged toolbox, runs an example with it, checks
%   the file it writes, and uninstalls the toolbox. Run it in a session with
%   nothing of Gamut on the path, so the package, the gateway and the core
%   all come from the toolbox:
%     matlab -batch "addpath('<checkout>/matlab/tests'); check_toolbox('Gamut.mltbx', '<checkout>/examples/matlab/one_mesh.m')"
if ~isempty(which('gamut_mex'))
    error('gamut:tests', 'a gateway is already on the path: %s', which('gamut_mex'));
end
addon = matlab.addons.install(toolbox);
cleanup = onCleanup(@() uninstall(addon));
fprintf('installed %s %s; the gateway is %s\n', addon.Name, addon.Version, which('gamut_mex'));
core = gamut_mex('version');
if ~strcmp(core, addon.Version)
    error('gamut:tests', 'the toolbox is version %s and its core %s', addon.Version, core);
end

folder = tempname;
mkdir(folder);
written = run_example(example, folder);
findings = gamut.validate(written);
if ~isempty(findings)
    error('gamut:tests', '%s breaks %s', written, strjoin({findings.rule}, ', '));
end
fprintf('%s is valid\n', written);
rmdir(folder, 's');
end

function written = run_example(example, folder)
% In a workspace of its own, so nothing it opened outlives the toolbox.
copyfile(example, folder);
[~, name, ext] = fileparts(example);
run(fullfile(folder, [name ext]));
found = dir(fullfile(folder, '*.gamut'));
written = fullfile(folder, found(1).name);
end

function uninstall(addon)
clear gamut_mex       % Windows cannot remove a library that is still loaded
matlab.addons.uninstall(addon.Identifier);
fprintf('uninstalled %s %s\n', addon.Name, addon.Version);
end
