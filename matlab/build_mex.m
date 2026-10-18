function build_mex(library)
%BUILD_MEX Builds the MATLAB gateway to the Gamut core.
%   build_mex                 % uses the core built in <checkout>/build
%   build_mex(library)        % a libgamut.dylib, libgamut.so or gamut.dll
%
%   The core library is copied beside the gateway, so this folder is all
%   MATLAB needs on its path. A core built with GAMUT_STATIC_HDF5 (as the
%   Python wheels are) carries its own HDF5 and never meets MATLAB's.
%   Needs a C++ compiler that `mex -setup C++` accepts.
here = fileparts(mfilename('fullpath'));
if nargin < 1 || isempty(library)
    names = {'libgamut.dylib', 'libgamut.so', 'gamut.dll'};
    library = '';
    for k = 1:numel(names)
        candidate = fullfile(here, '..', 'build', names{k});
        if isfile(candidate), library = candidate; break; end
        candidate = fullfile(here, '..', 'build', 'Release', names{k});
        if isfile(candidate), library = candidate; break; end
    end
    if isempty(library)
        error('gamut:usage', ['no core library in %s; build it first ' ...
            '(cmake -S . -B build && cmake --build build) or give its path'], ...
            fullfile(here, '..', 'build'));
    end
end
library = char(library);
if ~isfile(library)
    error('gamut:usage', 'no file %s', library);
end
[libdir, ~, ext] = fileparts(library);
copyfile(library, here);
if ~strcmp(ext, '.dll')
    % Keep the library's own name for the loader (and its link name).
    [~, base] = fileparts(library);
    linkname = regexprep(base, '^lib', '');
else
    linkname = 'gamut';
    implib = fullfile(libdir, 'gamut.lib');
end
include = fullfile(here, '..', 'include');
args = {'-largeArrayDims', ['-I' include], fullfile(here, 'gamut_mex.cpp'), ...
        '-output', fullfile(here, 'gamut_mex')};
if ismac
    args = [args, {['-L' here], ['-l' linkname], ...
            'CXXFLAGS=$CXXFLAGS -std=c++17', ...
            'LDFLAGS=$LDFLAGS -Wl,-rpath,@loader_path'}];
elseif isunix
    args = [args, {['-L' here], ['-l' linkname], ...
            'CXXFLAGS=$CXXFLAGS -std=c++17', ...
            'LDFLAGS=$LDFLAGS -Wl,-rpath,''$ORIGIN'''}];
else
    if ~isfile(implib)
        error('gamut:usage', 'no import library %s beside the DLL', implib);
    end
    args = [args, {'COMPFLAGS=$COMPFLAGS /std:c++17', implib}];
end
mex(args{:});
fprintf('built %s with the core %s\n', fullfile(here, ['gamut_mex.' mexext]), library);
end
