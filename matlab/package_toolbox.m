function package_toolbox(output)
%PACKAGE_TOOLBOX Packages the gateways built here as the Gamut toolbox.
%   package_toolbox('Gamut.mltbx')
%
%   The toolbox holds the gamut package and each gateway in this folder
%   (gamut_mex.mexa64, .mexmaca64, .mexw64) with its core library beside
%   it, so installing it needs no compiler; and the licences of HDF5 and
%   zlib, which the core links in. It claims the platforms of the gateways
%   it holds and this MATLAB's release and later: a gateway runs in the
%   release it was built with and later ones, so build the gateways with
%   this MATLAB.
here = fileparts(mfilename('fullpath'));
root = fileparts(here);

stage = tempname;
mkdir(stage);
cleanup = onCleanup(@() rmdir(stage, 's'));

platforms = {'Glnxa64', 'mexa64', 'libgamut.so'
             'Mac', 'mexmaca64', 'libgamut.dylib'
             'Win64', 'mexw64', 'gamut.dll'};
present = false(size(platforms, 1), 1);
for k = 1:numel(present)
    gateway = fullfile(here, ['gamut_mex.' platforms{k, 2}]);
    present(k) = isfile(gateway);
    if present(k)
        copyfile(gateway, stage);
        copyfile(fullfile(here, platforms{k, 3}), stage);
    end
end
if ~any(present)
    error('gamut:usage', 'no gateway in %s; build one with build_mex', here);
end
copyfile(fullfile(here, '+gamut'), fullfile(stage, '+gamut'));
copyfile(fullfile(root, 'licenses'), fullfile(stage, 'licenses'));
copyfile(fullfile(root, 'LICENSE'), stage);
mkdir(fullfile(stage, 'doc'));
copyfile(fullfile(root, 'examples', 'matlab', 'one_mesh.m'), ...
         fullfile(stage, 'doc', 'GettingStarted.m'));

cmake = fileread(fullfile(root, 'CMakeLists.txt'));
number = regexp(cmake, 'project\(gamut VERSION ([0-9.]+)', 'tokens', 'once');
% The same identifier in every version, or MATLAB installs a new version
% beside the old one instead of over it.
opts = matlab.addons.toolbox.ToolboxOptions(stage, '78cb4bf3-20e5-4c20-b7c3-a7ce3139556a');
opts.ToolboxName = 'Gamut';
opts.ToolboxVersion = number{1};
opts.AuthorName = 'Bijective Systems';
opts.Summary = 'An open file format for parametric simulation studies and the models fitted to them.';
opts.Description = ['Gamut is a file format for parametric simulation studies: the ' ...
    'hundreds or thousands of CFD or FEA runs behind a design sweep, an aerodynamic ' ...
    'database or a surrogate model. One file holds the run table, each run''s inputs, ' ...
    'results and status, and, when the runs have a mesh, the mesh and every field on ' ...
    'it, all with units. MATLAB, Python, Julia and C++ read and write it with the same ' ...
    'calls. The toolbox carries the compiled library, so it needs no compiler. Start ' ...
    'with gamut.create and gamut.open; help gamut.Study lists what a study can do.'];
opts.ToolboxMatlabPath = stage;
opts.ToolboxGettingStartedGuide = fullfile(stage, 'doc', 'GettingStarted.m');
opts.MinimumMatlabRelease = ['R' version('-release')];
for k = 1:numel(present)
    opts.SupportedPlatforms.(platforms{k, 1}) = present(k);
end
opts.SupportedPlatforms.MatlabOnline = false;
opts.OutputFile = output;
matlab.addons.toolbox.packageToolbox(opts);
fprintf('packaged Gamut %s for %s, MATLAB %s and later, as %s\n', opts.ToolboxVersion, ...
    strjoin(platforms(present, 1), ', '), opts.MinimumMatlabRelease, output);
end
