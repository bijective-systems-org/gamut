%PARTS Reading only what you need: rows by condition, nodes by zone.
%   Runs are chosen with a small expression language and nodes by a mesh
%   label. Values arrive in the units they were stored in; this program
%   converts them itself, where Python's reads convert on request.
%   examples/08_selecting_parts.py and the Julia and C++ examples are the
%   same program and print the same lines. Positions count from 1.
%   cylinderRing and cylinderPressure are beside this file.

[points, cells, t, r] = cylinderRing();
surface = int64(r == min(r));                                   % 1 on the wall
study = gamut.create('parts.gamut', 'writer', 'example parts', 'mesh', 'shared', 'per', 'fixed', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'condition'), ...
                         'speed', struct('units', 'm s-1', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'meshLabels', struct('surface', struct('at', 'node', 'categories', {{'field', 'wall'}})), ...
    'fields', struct('p', struct('units', 'Pa', 'at', 'node')));
study.setMesh(points, cells, struct('surface', surface));
for speed = [10 20 40]
    for gamma = [0 2 4]
        q = 0.5 * 1.225 * speed^2;                              % dynamic pressure, air at sea level
        study.addRun(struct('gamma', gamma, 'speed', speed, 'status', 'converged'), ...
            'fields', struct('p', q * cylinderPressure(t, r, 1, gamma)));
    end
end
study.close();

study = gamut.open('parts.gamut');
rows = study.select('speed >= 20 and gamma > 1 and status == converged');
fprintf('chosen: %d runs\n', numel(rows));
wall = find(strcmp(study.categories('surface'), 'wall')) - 1;    % the code that means 'wall'
onWall = find(study.getMeshLabel('surface') == wall);
pWall = study.getField('p', 'rows', rows, 'nodes', onWall) / 1000;   % stored in Pa; kPa
fprintf('wall pressure: %d runs x %d nodes, lowest %.3f kPa\n', size(pWall, 1), size(pWall, 2), min(pWall(:)));
speeds = study.getParameter('speed', 'rows', rows) * 3.6;            % stored in m s-1; km/h
fprintf('speeds in km/h:%s\n', sprintf(' %.1f', speeds));
study.close();
