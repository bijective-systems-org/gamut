%COMBINING Growing, splitting and rewriting files.
%   gamut.append adds one file's runs to another (the same declarations;
%   category names merged); gamut.extract keeps chosen runs as a new file,
%   their ids kept; gamut.writeCopy rewrites a file with the default layout,
%   keeping its identity. examples/09_combining_files.py and the Julia and
%   C++ examples are the same program and print the same lines. Positions
%   count from 1; row ids are the file's own, from 0.

sweep('monday.gamut', [0.5 0.6 0.7]);
sweep('tuesday.gamut', [0.8 0.9]);
fprintf('appended %d runs\n', gamut.append('monday.gamut', 'tuesday.gamut'));

study = gamut.open('monday.gamut');
good = study.select('status == converged');
study.close();
gamut.extract('monday.gamut', 'converged.gamut', good);
gamut.writeCopy('converged.gamut', 'converged_copy.gamut');

study = gamut.open('converged.gamut');
copy = gamut.open('converged_copy.gamut');
fprintf('kept ids:%s at mach%s\n', sprintf(' %d', study.getRowIds()), sprintf(' %g', study.getParameter('mach')));
answers = {'no', 'yes'};
fprintf('same file id after the rewrite: %s\n', answers{strcmp(study.describe().file_id, copy.describe().file_id) + 1});
study.close();
copy.close();
found = gamut.validate('converged.gamut');
fprintf('valid: %s\n', answers{(isempty(found) || ~any(startsWith({found.rule}, 'E'))) + 1});

function sweep(path, machs)
study = gamut.create(path, 'writer', 'example sweep', ...
    'parameters', struct('mach', struct('units', '1', 'role', 'condition')), ...
    'labels', struct('status', struct('role', 'status', 'categories', {{'converged', 'failed'}})), ...
    'scalars', struct('cd', '1'));
for mach = machs
    status = 'converged';
    if mach > 0.85, status = 'failed'; end
    study.addRun(struct('mach', mach, 'status', status, 'cd', 0.01 + 0.05 * max(0, mach - 0.7)^2));
end
study.close();
end
