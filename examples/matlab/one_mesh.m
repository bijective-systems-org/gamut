%ONE_MESH A sweep on one mesh: eight runs written, a ninth added, then read by condition.
%   Potential flow past a cylinder at nine values of circulation, on one
%   ring of quadrilaterals. examples/00_readme.py and the Julia and C
%   examples are the same program and print the same line. Positions
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
solve = @(gamma) 1 - ((cos(t) .* (1 - 1 ./ r.^2)).^2 ...                 % stands for the solver
                     + (-sin(t) .* (1 + 1 ./ r.^2) + gamma ./ (2 * pi * r)).^2);

study = gamut.create('cylinder.gamut', 'writer', 'example sweep', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'design')), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh(points, cells);
for gamma = linspace(0, 3.5, 8)
    study.addRun(struct('gamma', gamma), 'fields', struct('cp', solve(gamma)));
end
study.close();

study = gamut.open('cylinder.gamut', 'mode', 'a');
study.addRun(struct('gamma', 4), 'fields', struct('cp', solve(4)));
study.close();

study = gamut.open('cylinder.gamut');
rows = study.select('gamma > 2');
cp = study.getField('cp', 'rows', rows, 'nodes', 13);           % runs x nodes, from 1
study.close();
fprintf('cp on top of the cylinder where gamma > 2:%s\n', sprintf(' %.2f', cp));
