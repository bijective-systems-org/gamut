%REFINEMENT Runs on different meshes: a refinement study.
%   The same flow on three meshes of increasing resolution, with the
%   pressure stored per cell. examples/04_changing_mesh.py and the Julia
%   and C++ examples are the same program and print the same lines.
%   Positions count from 1. cylinderRing and cylinderPressure are beside
%   this file.

study = gamut.create('refinement.gamut', 'writer', 'example refinement', 'mesh', 'changing', 'per', 'run', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('cells_round', struct('units', '1', 'role', 'design')), ...
    'scalars', struct('cp_min', '1'), ...
    'fields', struct('cp', struct('units', '1', 'at', 'cell')));
for n = [24 48 96]
    [points, cells] = cylinderRing(1, n, n / 4);
    corners = reshape(cells{3}, 4, []) + 1;                         % four nodes per quad, from 1
    x = mean(reshape(points(corners, 1), 4, []))';
    y = mean(reshape(points(corners, 2), 4, []))';
    cp = cylinderPressure(atan2(y, x), hypot(x, y), 1, 0);
    study.addRun(struct('cells_round', n, 'cp_min', min(cp)), 'fields', struct('cp', cp), ...
        'points', points, 'cells', cells);
end
study.close();

study = gamut.open('refinement.gamut');
rounds = study.getParameter('cells_round');
for row = 1:study.rowCount()
    types = study.getCells(row);
    cp = study.getField('cp', 'rows', row);
    fprintf('%g cells round: %d nodes, %d cells, lowest cell cp %.3f\n', rounds(row), ...
        size(study.getPoints(row), 1), numel(types), min(cp));
end
study.close();
