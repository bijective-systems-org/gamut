function findings = validate(path)
%VALIDATE Every rule of the format the file breaks, as a struct array with
%   fields rule, severity, path and message (empty when the file is clean).
findings = mestra_mex('validate', path);
end
