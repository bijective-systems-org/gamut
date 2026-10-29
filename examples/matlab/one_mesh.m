%ONE_MESH A sweep on one mesh: eight runs written, a ninth added, then read.
%   Potential flow past a cylinder at nine values of circulation, on one
%   ring of quadrilaterals. The Python, Julia and C++ examples of this name
%   are the same program and print the same lines. Positions
%   (runs, nodes, cells) are 1-based; the node numbers inside cells stay
%   0-based, as in VTK and every other language.

nTheta = 48; nR = 12;
theta = linspace(0, 2 * pi, nTheta + 1); theta = theta(1:end - 1);
[t, r] = ndgrid(theta, logspace(0, log10(6), nR));    % around each ring first
t = t(:); r = r(:);
points = [r .* cos(t), r .* sin(t)];
[i, j] = ndgrid(0:nTheta - 1, 0:nR - 2);
i = i(:); j = j(:);
quads = [j * nTheta + i, j * nTheta + mod(i + 1, nTheta), ...
         (j + 1) * nTheta + mod(i + 1, nTheta), (j + 1) * nTheta + i]';
cells = {repmat(uint8(9), 1, numel(i)), 0:4:4 * numel(i), quads(:)'};   % VTK quadrilaterals
surface = int64((1:numel(t))' <= nTheta);                               % 1 ('wall') on the first ring
solve = @(gamma) 1 - ((cos(t) .* (1 - 1 ./ r.^2)).^2 ...                 % stands for the solver
                     + (-sin(t) .* (1 + 1 ./ r.^2) + gamma ./ (2 * pi * r)).^2);

study = gamut.create('cylinder.gamut', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'meshLabels', struct('surface', struct('at', 'node', 'categories', {{'field', 'wall'}})), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells, struct('surface', surface));
for gamma = linspace(0, 3.5, 8)
    study.addRun(struct('gamma', gamma), 'fields', struct('cp', solve(gamma)));
end
study.close();

study = gamut.open('cylinder.gamut', 'mode', 'a');
study.addRun(struct('gamma', 4), 'fields', struct('cp', solve(4)));
study.close();

study = gamut.open('cylinder.gamut');
fprintf('%s mesh, %d runs, %d nodes\n', study.type(), study.rowCount(), size(study.getPoints(), 1));
wall = find(strcmp(study.categories('surface'), 'wall')) - 1;  % the code that means 'wall'
onWall = find(study.getMeshLabel('surface') == wall);
lowest = min(study.getField('cp', 'nodes', onWall), [], 2);    % runs x wall nodes; each run's lowest
fprintf('lowest cp on the wall, by run:%s\n', sprintf(' %.2f', lowest));
top = study.getField('cp', 'nodes', 13);                       % node 13, the top, in every run
study.close();
fprintf('cp at the top of the cylinder, run by run:%s\n', sprintf(' %.2f', top));
