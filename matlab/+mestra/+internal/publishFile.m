function publishFile(source, target)
%publishFile  Publish a closed sibling file without deleting the target.
%   ATOMIC_MOVE either replaces the directory entry or fails. Do not
%   fall back to movefile: a non-atomic move has no failure-preservation
%   contract. See java.nio.file.Files.move's ATOMIC_MOVE documentation.
    if ~usejava('jvm')
        error('mestra:write', ...
              'checked writes require the JVM for atomic file replacement');
    end
    options = javaArray('java.nio.file.CopyOption', 1);
    options(1) = java.nio.file.StandardCopyOption.ATOMIC_MOVE;
    % Both names are resolved against MATLAB's current folder here. Java
    % takes a relative path from the folder MATLAB started in, which cd
    % does not move: on macOS and Linux the operating system resolves it
    % against the process's folder, which cd does move, but on Windows
    % Java resolves it itself, so a write to a relative name found its
    % staged file missing (NoSuchFileException).
    here = java.io.File(pwd).toPath();
    from = here.resolve(char(source));
    to = here.resolve(char(target));
    try
        java.nio.file.Files.move(from, to, options);
    catch cause
        problem = MException('mestra:write', ...
            'could not atomically publish the file at %s: %s', target, cause.message);
        throw(addCause(problem, cause));
    end
end
