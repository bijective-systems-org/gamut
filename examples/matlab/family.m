%FAMILY A family of geometries that share one mesh topology.
%   Three cylinders of different radius, meshed with the same topology, so
%   node k is the same place on every member, each run at three
%   circulations. examples/03_geometry_family.py and the Julia and C++
%   examples are the same program and print the same lines. Positions
%   count from 1. cylinderRing and cylinderPressure are beside this file.

names = {'slim', 'base', 'wide'};
radii = [0.8 1.0 1.2];
[base, cells] = cylinderRing();

study = gamut.create('family.gamut', 'writer', 'example family', 'mesh', 'shared', 'per', 'group:member', ...
    'coordinates', struct('units', 'm', 'axes', 2), ...
    'labels', struct('member', struct('role', 'group', 'categories', {names}), ...
                     'split', struct('role', 'split', 'categories', {{'train', 'test'}})), ...
    'generalisationGroup', 'member', ...
    'parameters', struct('gamma', struct('units', 'm2 s-1', 'role', 'condition')), ...
    'fields', struct('cp', struct('units', '1', 'at', 'node')));
study.setMesh([], cells, struct(), size(base, 1));
for k = 1:numel(names)
    [points, ~, t, r] = cylinderRing(radii(k));
    for gamma = [0 2 4]
        split = 'train';
        if strcmp(names{k}, 'wide'), split = 'test'; end
        study.addRun(struct('member', names{k}, 'gamma', gamma, 'split', split), ...
            'fields', struct('cp', cylinderPressure(t, r, radii(k), gamma)), 'points', points);
    end
end
study.close();

study = gamut.open('family.gamut');
fprintf('%d runs on %d members of one topology\n', study.rowCount(), numel(names));
for k = 1:numel(names)
    rows = study.select(sprintf('member == %s', names{k}));
    points = study.getPoints(rows(1));
    fprintf('  %s: first node at x = %.2f m\n', names{k}, points(1, 1));
end
cp = study.getField('cp', 'nodes', 1);
fprintf('cp at the first node, run by run:%s\n', sprintf(' %.2f', cp));
test = study.select('split == test');
fprintf('held out for testing: %d runs of %s\n', numel(test), ...
    strjoin(unique(study.getLabel('member', 'rows', test)), ', '));
study.close();
