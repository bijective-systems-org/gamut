% Holds the MATLAB binding to the cross-language corpus (corpus/).
%   matlab -batch "corpus='<dir>'; run('<abs>/matlab/tests/check_corpus.m')"
here = fileparts(mfilename('fullpath'));
addpath(fileparts(here));
expected = jsondecode(fileread(fullfile(corpus, 'expected.json')));
names = fieldnames(expected);
fails = {};
counts = struct('valid', 0, 'rules', 0, 'hostile', 0);
for k = 1:numel(names)
    name = names{k};
    e = expected.(name);
    path = fullfile(corpus, [name '.gamut']);
    counts.(e.group) = counts.(e.group) + 1;
    try
        f = gamut.validate(path);
    catch err
        fails{end + 1} = sprintf('%s: validate raised %s', name, err.message); %#ok<SAGROW>
        continue
    end
    found = {};
    if ~isempty(f), found = {f.rule}; end
    if strcmp(e.group, 'valid')
        if ~isempty(found)
            fails{end + 1} = sprintf('%s: a valid file drew %s', name, strjoin(found, ' ')); %#ok<SAGROW>
        end
        if isfield(e, 'probes')
            probes = e.probes;
            if ~iscell(probes), probes = num2cell(probes); end
            for j = 1:numel(probes)
                why = probe(path, probes{j});
                if ~isempty(why), fails{end + 1} = sprintf('%s: %s', name, why); end %#ok<SAGROW>
            end
        end
    else
        rules = e.rules;
        if ischar(rules), rules = {rules}; end
        if isempty(rules), rules = {}; end   % jsondecode gives [] for an empty list
        % A rule case breaks exactly its rules; a hostile case may draw more.
        missing = setdiff(rules, found);
        extra = {};
        if strcmp(e.group, 'rules'), extra = setdiff(found, rules); end
        if ~isempty(missing) || ~isempty(extra)
            fails{end + 1} = sprintf('%s: expected %s, found %s', name, strjoin(rules, ' '), ...
                strjoin(unique(found), ' ')); %#ok<SAGROW>
        end
        if strcmp(e.group, 'hostile')
            why = hostile(path, e);
            if ~isempty(why), fails{end + 1} = sprintf('%s: %s', name, why); end %#ok<SAGROW>
        end
    end
end
total = counts.valid + counts.rules + counts.hostile;
fprintf('%d cases (%d valid, %d rule, %d hostile): %d hold\n', total, counts.valid, ...
    counts.rules, counts.hostile, total - numel(fails));
for k = 1:numel(fails), fprintf('  FAIL %s\n', fails{k}); end
if ~isempty(fails), error('gamut:corpus', '%d failures', numel(fails)); end

function why = hostile(path, e)
% Opened and read without a crash: a refusal is a Gamut error, with the
% expected rule when the case names one.
why = '';
try
    r = gamut.open(path);
    c = onCleanup(@() r.close());
    r.names('parameters');
    if isfield(e, 'reads')
        reads = e.reads;
        if ~iscell(reads), reads = num2cell(reads); end
        for j = 1:numel(reads)
            q = reads{j};
            try
                if isfield(q, 'label'), r.getLabel(q.label);
                elseif isfield(q, 'cells'), r.getCells(q.cells + 1);
                elseif isfield(q, 'select'), r.select(q.select);
                elseif isfield(q, 'scalar'), r.getScalar(q.scalar);
                elseif isfield(q, 'evaluate')
                    out = gamut.evaluate(path, q.evaluate);
                    out.close();
                end
            catch err
                if ~startsWith(err.identifier, 'gamut:'), rethrow(err); end
            end
        end
    end
    if isfield(e, 'refused')
        why = sprintf('opened; expected refusal %s', e.refused);
    end
catch err
    if ~startsWith(err.identifier, 'gamut:')
        why = sprintf('raised %s: %s', err.identifier, err.message);
    elseif isfield(e, 'refused') && ~strcmp(err.identifier, ['gamut:' e.refused])
        why = sprintf('refused with %s, expected %s', err.identifier, e.refused);
    end
end
end

function why = described(f, p)
% A file-level attribute as describe gives it; absent when the probe's
% value is null (an empty array from jsondecode).
why = '';
d = f.describe();
if isfield(d, p.describe), got = d.(p.describe); else, got = []; end
if ~isequal(got, p.value)
    why = sprintf('describe %s: %s ~= %s', p.describe, mat2str(got), mat2str(p.value));
end
end

function why = probe(path, p)
why = '';
if isfield(p, 'evaluate')
    out = gamut.evaluate(path, p.evaluate);
    c = onCleanup(@() out.close());
    if isfield(p, 'describe')
        why = described(out, p);
        return
    end
    got = out.getScalar(p.scalar);
    want = p.values(:);
    if ~isequal(got(:), want)
        why = sprintf('evaluate %s: %s ~= %s', p.scalar, mat2str(got(:)'), mat2str(want'));
    end
    return
end
if isfield(p, 'copy')
    tmp = tempname; mkdir(tmp);
    ct = onCleanup(@() rmdir(tmp, 's'));
    dst = fullfile(tmp, 'copy.gamut');
    if strcmp(p.copy, 'extract')
        gamut.extract(path, dst, p.rows(:)' + 1);
    else
        gamut.writeCopy(path, dst);
    end
    f = gamut.open(dst);
    cf = onCleanup(@() f.close());
    why = described(f, p);
    return
end
r = gamut.open(path);
c = onCleanup(@() r.close());
if isfield(p, 'describe')
    why = described(r, p);
    return
end
if isfield(p, 'info')
    switch p.info
        case 'type', got = r.type();
        case 'kind', got = r.kind();
        case 'addons', got = r.addons()';
    end
    want = p.value;
    if iscell(want) || isstring(want), want = cellstr(want(:)); got = cellstr(got(:)); end
    if ~isequal(got, want), why = sprintf('info %s differs', p.info); end
    return
end
if isfield(p, 'label')
    got = r.getLabel(p.label);
    if ~isequal(got(:)', p.names(:)'), why = sprintf('label %s differs', p.label); end
    return
end
if isfield(p, 'select')
    got = r.select(p.select) - 1;
    if ~isequal(got(:)', p.positions(:)'), why = 'select differs'; end
    return
end
codes = struct('float64', 6, 'float32', 5, 'int64', 4);
rows = []; sites = [];
if isfield(p, 'rows') && ~isempty(p.rows), rows = double(p.rows(:)); end
if isfield(p, 'sites') && ~isempty(p.sites), sites = double(p.sites(:)); end
got = gamut_mex('read', r.Handle, p.read, rows, sites, codes.(p.dtype));
want = p.values;
if strcmp(p.dtype, 'float32'), want = single(want); end
if strcmp(p.dtype, 'int64'), want = int64(want); end
% jsondecode gives nested lists as matrices in row order; compare values.
g = got(:); w = want(:);
if numel(g) ~= numel(w)
    why = sprintf('read %s: %d values, expected %d', p.read, numel(g), numel(w));
    return
end
gr = reshape(permute(got, ndims(got):-1:1), [], 1);
wr = reshape(permute(want, ndims(want):-1:1), [], 1);
if ~isequal(gr, wr) && ~isequal(g, w)
    why = sprintf('read %s differs', p.read);
end
end
