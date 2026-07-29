function export_quantum_dynamics_matlab(repository_root, output_root)
% Run the two pinned official scripts and export their numerical workspaces.
%
% Example:
%   matlab -batch "addpath('paper_replication_tasks/curation_tools'); ...
%     export_quantum_dynamics_matlab('/path/to/repository','/tmp/matlab-output')"

arguments
    repository_root (1,1) string
    output_root (1,1) string
end

repository_root = char(repository_root);
output_root = char(output_root);
required = {
    'OpenIsingModelTwoSpins.m'
    'TwoLevelSystemCoupledToLightBath.m'
    'sortingEigenvalues.m'
};
for index = 1:numel(required)
    candidate = fullfile(repository_root, required{index});
    assert(isfile(candidate), 'Missing pinned source file: %s', candidate);
end
if ~isfolder(output_root)
    mkdir(output_root);
end

old_visibility = get(groot, 'defaultFigureVisible');
cleanup = onCleanup(@() set(groot, 'defaultFigureVisible', old_visibility));
set(groot, 'defaultFigureVisible', 'off');
addpath(repository_root);

open_ising = run_open_ising(repository_root);
save(fullfile(output_root, 'open_ising.mat'), '-struct', 'open_ising', '-v7');
close all force;

light_bath = run_light_bath(repository_root);
save(fullfile(output_root, 'light_bath.mat'), '-struct', 'light_bath', '-v7');
close all force;
end

function result = run_open_ising(repository_root)
run(fullfile(repository_root, 'OpenIsingModelTwoSpins.m'));
result.times = reshape(t, 1, []);
result.observables = [reshape(real(Mz), 1, []); ...
    reshape(exp(real(lambda_sort(end)) .* t), 1, [])];
result.eigenvalues = reshape(lambda_sort, [], 1);
end

function result = run_light_bath(repository_root)
run(fullfile(repository_root, 'TwoLevelSystemCoupledToLightBath.m'));
result.times = reshape(t, 1, []);
result.observables = [reshape(real(pe), 1, []); ...
    reshape(real(pe_exact), 1, []); ...
    reshape(imag(sigmap), 1, []); ...
    reshape(imag(sp_exact), 1, [])];
result.eigenvalues = reshape(lambda_sort, [], 1);
end
