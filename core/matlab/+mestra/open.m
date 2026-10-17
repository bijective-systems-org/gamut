function s = open(path, varargin)
%OPEN Opens a file to read, or with 'mode', 'a' to add runs in place.
%   s = mestra.open(path)                 % read
%   s = mestra.open(path, 'threads', 4)   % read, decompressing in 4 threads
%   s = mestra.open(path, 'mode', 'a')    % add runs
p = inputParser;
p.addParameter('mode', 'r');
p.addParameter('threads', 1);
p.parse(varargin{:});
switch p.Results.mode
    case 'r'
        h = mestra_mex('open', path);
        if p.Results.threads ~= 1
            mestra_mex('set_threads', h, p.Results.threads);
        end
        s = mestra.Study(h, path, false, '', '');
    case 'a'
        r = mestra.open(path);
        kind = r.MeshKind; per = r.Per;
        r.close();
        h = mestra_mex('open_append', path);
        s = mestra.Study(h, path, true, kind, per);
    otherwise
        error('mestra:usage', 'mode is ''r'' or ''a''');
end
end
