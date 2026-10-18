function build_mex(library)
%BUILD_MEX Builds the MATLAB gateway to the mestra core.
%   build_mex                 % uses the core built in <checkout>/build
%   build_mex(library)        % a libmestra.dylib, libmestra.so or mestra.dll
%
%   The core library is copied beside the gateway, so this folder is all
%   MATLAB needs on its path. A core built with MESTRA_STATIC_HDF5 (as the
%   Python wheels are) carries its own HDF5 and never meets MATLAB's.
%   Needs a C++ compiler that `mex -setup C++` accepts.
here = fileparts(mfilename('fullpath'));
if nargin < 1 || isempty(library)
    names = {'libmestra.dylib', 'libmestra.so', 'mestra.dll'};
    library = '';
    for k = 1:numel(names)
        candidate = fullfile(here, '..', 'build', names{k});
        if isfile(candidate), library = candidate; break; end
        candidate = fullfile(here, '..', 'build', 'Release', names{k});
        if isfile(candidate), library = candidate; break; end
    end
    if isempty(library)
        error('mestra:usage', ['no core library in %s; build it first ' ...
            '(cmake -S . -B build && cmake --build build) or give its path'], ...
            fullfile(here, '..', 'build'));
    end
end
library = char(library);
if ~isfile(library)
    error('mestra:usage', 'no file %s', library);
end
[libdir, ~, ext] = fileparts(library);
copyfile(library, here);
if ~strcmp(ext, '.dll')
    % Keep the library's own name for the loader (and its link name).
    [~, base] = fileparts(library);
    linkname = regexprep(base, '^lib', '');
else
    linkname = 'mestra';
    implib = fullfile(libdir, 'mestra.lib');
end
include = fullfile(here, '..', 'include');
args = {'-largeArrayDims', ['-I' include], fullfile(here, 'mestra_mex.cpp'), ...
        '-output', fullfile(here, 'mestra_mex')};
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
        error('mestra:usage', 'no import library %s beside the DLL', implib);
    end
    args = [args, {'COMPFLAGS=$COMPFLAGS /std:c++17', implib}];
end
mex(args{:});
fprintf('built %s with the core %s\n', fullfile(here, ['mestra_mex.' mexext]), library);
end
