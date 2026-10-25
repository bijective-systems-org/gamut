function s = create(path, varargin)
%CREATE Creates a data file and returns it open to add runs.
%   s = gamut.create(path, 'writer', name, 'parameters', P, 'labels', L, ...
%       'scalars', S, 'fields', F, 'meshLabels', M, 'constants', C, ...
%       'mesh', 'shared'|'changing', 'per', 'fixed'|'run'|'group:<label>', ...
%       'coordinates', struct('units', 'm', 'axes', 3), 'precision', struct(...), ...
%       'title', t, 'license', l, 'references', r, 'source', src, ...
%       'portionMarking', m, 'generalisationGroup', label, 'compression', true)
p = inputParser;
p.addParameter('writer', '');
p.addParameter('parameters', struct());
p.addParameter('labels', struct());
p.addParameter('scalars', struct());
p.addParameter('fields', struct());
p.addParameter('meshLabels', struct());
p.addParameter('constants', struct());
p.addParameter('mesh', '');
p.addParameter('per', '');
p.addParameter('coordinates', []);
p.addParameter('precision', struct());
p.addParameter('title', []);
p.addParameter('license', []);
p.addParameter('references', []);
p.addParameter('source', []);
p.addParameter('portionMarking', []);
p.addParameter('generalisationGroup', []);
p.addParameter('compression', true);
p.parse(varargin{:});
o = p.Results;
if isempty(o.writer)
    error('gamut:usage', 'name the program writing the file: ''writer''');
end
h = gamut_mex('create', path, o.writer, o.mesh, o.per);
s = gamut.Study(h, path, true, o.mesh, o.per);
if ~isempty(o.coordinates)
    s.Axes = gamut.internal.field(o.coordinates, 'axes', 3);
end
try
    gamut.internal.declare(h, o);
catch err
    % A half-declared file is not wanted; the declaration error stands.
    s.abandon(true);
    rethrow(err);
end
end
