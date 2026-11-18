%READ_WITH_NCREAD Read first.gamut with MATLAB's netCDF reader.
%   Run sweep.m first to create the file.

f = 'first.gamut';
cl = ncread(f, 'cl');
fprintf('cl: %s\n', strjoin(compose('%.2f', cl), ' '));
