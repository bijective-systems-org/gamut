%ONE_MESH Fields on one mesh shared by every run, from MATLAB.
%   The study of examples/02_one_mesh.py: potential flow past a cylinder at
%   nine values of circulation, on one ring of quadrilaterals. Positions
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
surface = [ones(1, nTheta), zeros(1, nTheta * (nR - 1))];                % wall: the first ring

study = mestra.create('cylinder.mes', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'meshLabels', struct('surface', struct('at', 'node', 'categories', {{'field', 'wall'}})), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells, struct('surface', surface));
for gamma = linspace(0, 4, 9)
    uTheta = -sin(t) .* (1 + 1 ./ r.^2) + gamma ./ (2 * pi * r);
    uR = cos(t) .* (1 - 1 ./ r.^2);
    study.addRun(struct('gamma', gamma), 'fields', struct('cp', 1 - (uR.^2 + uTheta.^2)));
end
study.close();

study = mestra.open('cylinder.mes');
fprintf('%s mesh, %d runs, %d nodes\n', study.type(), study.rowCount(), size(study.getPoints(), 1));
cp = study.getField('cp');                                       % runs x nodes
fprintf('cp block: %d x %d\n', size(cp));
wall = find(strcmp(study.categories('surface'), 'wall')) - 1;   % the code that means "wall"
onWall = find(study.getMeshLabel('surface') == wall);
lowest = min(study.getField('cp', 'nodes', onWall), [], 2);
fprintf('lowest cp on the wall, by run: %s\n', mat2str(round(lowest', 2)));
fprintf('one node across every run: %s\n', mat2str(round(study.getField('cp', 'nodes', 13)', 2)));
study.close();
