function s = createModel(path, varargin)
%CREATEMODEL Creates a model file (no runs) and returns it open to write.
%   s = gamut.createModel(path, 'writer', name, ...
%       'parameters', P, 'labels', L, 'scalars', S, 'fields', F, ...
%       'constants', C, 'mesh', 'shared', 'per', 'fixed'|'run', ...
%       'coordinates', struct('units', 'm', 'axes', 3), ...
%       'trainedOn', {fileIds}, 'title', t, 'license', l, ...
%       'references', r, 'source', src)
%   Parameters carry bounds (lower, upper); every scalar and field names
%   the model and output that computes it.  Then s.setMesh(...) when there
%   is a mesh, s.addModel(id, model, inputs) for each model, s.close().
p = inputParser;
p.addParameter('writer', '');
p.addParameter('parameters', struct());
p.addParameter('labels', struct());
p.addParameter('scalars', struct());
p.addParameter('fields', struct());
p.addParameter('meshLabels', struct());
p.addParameter('constants', struct());
p.addParameter('mesh', '');
p.addParameter('per', 'fixed');
p.addParameter('coordinates', []);
p.addParameter('precision', struct());
p.addParameter('trainedOn', {});
p.addParameter('title', []);
p.addParameter('license', []);
p.addParameter('references', []);
p.addParameter('source', []);
p.parse(varargin{:});
o = p.Results;
if isempty(o.writer)
    error('gamut:usage', 'name the program writing the file: ''writer''');
end
h = gamut_mex('create_model', path, o.writer, o.mesh, o.per);
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
