from mbi import Dataset, Domain
import numpy as np
import sys,os
import time
import pandas as pd
# from solvers.MIP_FEM0 import ftpl_best_response
import multiprocessing as mp
import matplotlib.pyplot as plt
import oracle
import util
from tqdm import tqdm


def gen_fake_data(fake_data, qW, neg_qW, noise, domain, alpha, s):
    assert noise.shape[0] == s
    for i in range(s):
        x = oracle.solve(qW, neg_qW, noise[i,:], domain, alpha)
        fake_data.append(x)


def generate(data, query_manager, epsilon, epsilon_0, exponential_scale, samples, alpha=0, show_prgress=True):
    domain = data.domain
    D = np.sum(domain.shape)
    N = data.df.shape[0]
    Q_size = query_manager.num_queries
    delta = 1.0 / N ** 2
    beta = 0.05  ## Fail probability

    prev_queries = []
    neg_queries = []
    rho_comp = 0.0000

    q1 = util.sample(np.ones(Q_size) / Q_size)
    q2 = util.sample(np.ones(Q_size) / Q_size)
    prev_queries.append(q1)  ## Sample a query from the uniform distribution
    neg_queries.append(q2)  ## Sample a query from the uniform distribution

    real_answers = query_manager.get_answer(data, debug=False)
    neg_real_answers = 1 - real_answers

    final_syn_data = []
    t = -1
    start_time = time.time()
    temp = []
    if show_prgress:
        # progress = tqdm(total=0.5 * epsilon ** 2)
        progress = tqdm(total=epsilon)
    last_eps = 0
    while True:
        """
        End early after 10 minutes
        """
        if time.time() - start_time > 600: break

        t += 1
        rho = 0.5 * epsilon_0 ** 2
        rho_comp += rho  ## EM privacy
        current_eps = rho_comp + 2 * np.sqrt(rho_comp * np.log(1 / delta))

        if current_eps > epsilon:
            break
        if show_prgress:
            progress.update(current_eps-last_eps)
            last_eps = current_eps
        """
        Sample s times from FTPL
        """
        util.blockPrint()
        num_processes = 8
        s2 = int(1.0 + samples / num_processes)
        samples_rem = samples
        processes = []
        manager = mp.Manager()
        fake_temp = manager.list()

        query_workload = query_manager.get_query_workload(prev_queries)
        neg_query_workload = query_manager.get_query_workload(neg_queries)

        for i in range(num_processes):
            temp_s = samples_rem if samples_rem - s2 < 0 else s2
            samples_rem -= temp_s
            noise = np.random.exponential(exponential_scale, (temp_s, D))
            proc = mp.Process(target=gen_fake_data,
                              args=(fake_temp, query_workload, neg_query_workload, noise, domain, alpha, temp_s))

            proc.start()
            processes.append(proc)

        assert samples_rem == 0, "samples_rem = {}".format(samples_rem)
        for p in processes:
            p.join()

        util.enablePrint()
        oh_fake_data = []
        assert len(fake_temp) > 0
        for x in fake_temp:
            oh_fake_data.append(x)
            temp.append(x)
            if current_eps >= epsilon / 2:  ## this trick haves the final error
                final_syn_data.append(x)

        assert len(oh_fake_data) == samples, "len(D_hat) = {} len(fake_data_ = {}".format(len(oh_fake_data), len(fake_temp))
        for i in range(samples):
            assert len(oh_fake_data[i]) == D, "D_hat dim = {}".format(len(D_hat[0]))
        assert not final_syn_data or len(final_syn_data[0]) == D, "D_hat dim = {}".format(len(oh_fake_data[0]))

        fake_data = Dataset(pd.DataFrame(util.decode_dataset(oh_fake_data, domain), columns=domain.attrs), domain)

        """
        Compute Exponential Mechanism distribution
        """
        fake_answers = query_manager.get_answer(fake_data, debug=False)
        neg_fake_answers = 1 - fake_answers

        score = np.append(real_answers - fake_answers, neg_real_answers - neg_fake_answers)

        EM_dist_0 = np.exp(epsilon_0 * score * N / 2, dtype=np.float128)
        sum = np.sum(EM_dist_0)
        assert sum > 0 and not np.isinf(sum)
        EM_dist = EM_dist_0 / sum
        assert not np.isnan(EM_dist).any(), "EM_dist_0 = {} EM_dist = {} sum = {}".format(EM_dist_0, EM_dist, sum)
        assert not np.isinf(EM_dist).any(), "EM_dist_0 = {} EM_dist = {} sum = {}".format(EM_dist_0, EM_dist, sum)

        """
        Sample from EM
        """
        q_t_ind = util.sample(EM_dist)

        if q_t_ind < Q_size:
            prev_queries.append(q_t_ind)
        else:
            neg_queries.append(q_t_ind - Q_size)

    if len(final_syn_data) == 0:
        final_syn_data = temp
    fake_data = Dataset(pd.DataFrame(util.decode_dataset(final_syn_data, domain), columns=domain.attrs), domain)

    return fake_data

# if __name__ == "__main__":
#     d = Domain(('A', 'B', 'C'), (2, 2, 2))
#     data = Dataset.synthetic(d, 10)
#     print("test", data.df)
