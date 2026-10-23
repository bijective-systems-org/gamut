%READ_WITH_NCREAD The sweep read with MATLAB's own netCDF functions, with
%   no Gamut package and no compiler: a study file is netCDF-4. Values come
%   in the units they were stored in (ncreadatt names them), a label comes
%   as its codes, which count from 0, and its names are its table under
%   /categories. Reads sweep.gamut, which the sweep example writes, and
%   prints the same line.

f = 'sweep.gamut';
cl = ncread(f, 'cl');                                % one value per run
names = ncread(f, '/categories/status');             % the status names
status = names(ncread(f, 'status') + 1);             % each run's status
converged = status == "converged";
fprintf('lift of the runs that converged: %s\n', strjoin(compose('%.2f', cl(converged)), ' '));
