function s = spec(value)
%SPEC A declaration given as text (its units) or as a struct.
if ischar(value) || isstring(value)
    s = struct('units', char(value));
else
    s = value;
end
end
