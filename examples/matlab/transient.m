%TRANSIENT Transient runs: every saved step is a row.
%   Two transient runs, each saved at 101 time steps. Time is a parameter
%   with the role time, and a group label says which run each step belongs
%   to. examples/05_time_series.py and the Julia and C++ examples are the
%   same program and print the same lines. Positions count from 1.

steps = linspace(0, 10, 101)';
study = gamut.create('transient.gamut', 'writer', 'example transient', ...
    'labels', struct('run', struct('role', 'group')), ...
    'parameters', struct('t', struct('units', 's', 'role', 'time', 'runGroup', 'run'), ...
                         'speed', struct('units', 'm s-1', 'role', 'condition')), ...
    'scalars', struct('cl', '1'));
runs = {'slow', 20; 'fast', 35};
for k = 1:size(runs, 1)
    speed = runs{k, 2};
    frequency = 0.2 * speed / 10;                                   % shedding, Strouhal 0.2
    cl = 0.8 * sin(2 * pi * frequency * steps) .* (1 - exp(-steps));
    study.addRuns(struct('run', {repmat(runs(k, 1), numel(steps), 1)}, 't', steps, ...
        'speed', repmat(speed, numel(steps), 1), 'cl', cl));
end
study.close();

study = gamut.open('transient.gamut');
fprintf('%d rows, %d runs\n', study.rowCount(), numel(study.categories('run')));
fast = study.select('run == fast');
t = study.getParameter('t', 'rows', fast);
cl = study.getScalar('cl', 'rows', fast);
[peak, k] = max(abs(cl));
fprintf('fast run: %d steps, peak |cl| %.2f at t = %.1f s\n', numel(fast), peak, t(k));
study.close();
