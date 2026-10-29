function s = open(path, varargin)
%OPEN Opens a file to read, or with 'mode', 'a' to add runs in place.
%   s = gamut.open(path)                 % read
%   s = gamut.open(path, 'threads', 4)   % read, decompressing in 4 threads
%   s = gamut.open(path, 'mode', 'a')    % add runs
p = inputParser;
p.addParameter('mode', 'r');
p.addParameter('threads', 1);
p.parse(varargin{:});
switch p.Results.mode
    case 'r'
        h = gamut_mex('open', path);
        s = gamut.Study(h, path, false, '', '');   % owns the handle, so a refusal closes it
        if p.Results.threads ~= 1
            try
                gamut_mex('set_threads', h, p.Results.threads);
            catch err
                s.close();
                rethrow(err);
            end
        end
    case 'a'
        r = gamut.open(path);
        kind = r.MeshKind; per = r.Per;
        r.close();
        h = gamut_mex('open_append', path);
        s = gamut.Study(h, path, true, kind, per);
    otherwise
        error('gamut:usage', 'mode is ''r'' or ''a''');
end
end
