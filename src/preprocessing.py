
import numpy, pandas, scipy, seaborn, math, time, umap, h5py, json
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from matplotlib import pyplot
from sklearn.preprocessing import RobustScaler

# constants
user = 'andreidm'
path = '/Users/{}/ETH/projects/normalization/data/'.format(user)
min_relevant_intensity = 1000
batches = ['0108', '0110', '0124', '0219', '0221', '0304', '0306']
sps = []  # set shared perturbations


def split_to_train_and_test(values, batches, scaler, proportion=0.7):
    """ Split data for the classifier of the adversarial training loop. """

    n_samples, n_features = values.shape

    # scale
    scaled = scaler.transform(values)
    # split values to train and val
    x_train = scaled[:int(proportion * n_samples), :]
    x_val = scaled[int(proportion * n_samples):, :]
    y_train = batches[:int(proportion * n_samples)]
    y_val = batches[int(proportion * n_samples):]

    if numpy.min(batches) == 1:
        # enumerate batches from 0 to n
        y_train -= 1
        y_val -= 1

    return x_train, x_val, y_train, y_val


def run_pca(data, n=100):

    transformer = PCA(n_components=n)
    scaler = StandardScaler()

    scaled_data = scaler.fit_transform(data)
    reduced_data = transformer.fit_transform(scaled_data)

    print(reduced_data.shape)

    # percent of variance explained
    print(list(transformer.explained_variance_ratio_ * 100))

    return reduced_data, transformer


def run_umap(data, full_samples_names, neighbors=15, metric='cosine', min_dist=0.1, scale=False, annotate=False):

    random_seed = 905

    if scale:
        start = time.time()
        data = StandardScaler().fit_transform(data)
        print('scaling took {} s'.format(time.time() - start))

    seaborn.set(font_scale=.8)
    seaborn.color_palette('colorblind')
    # seaborn.axes_style('whitegrid')

    reducer = umap.UMAP(n_neighbors=neighbors, metric=metric, min_dist=min_dist, random_state=random_seed)
    start = time.time()
    embedding = reducer.fit_transform(data)
    print('umap transform with n = {} took {} s'.format(neighbors, time.time() - start))

    # for batch coloring
    batch_ids = [name.split('_')[3] for name in full_samples_names]

    pyplot.figure(figsize=(8, 6))
    seaborn.scatterplot(x=embedding[:, 0], y=embedding[:, 1], hue=batch_ids, alpha=1., palette=seaborn.color_palette('colorblind', n_colors=len(set(batch_ids))))
    pyplot.title('UMAP on QC features: n={}, metric={}'.format(neighbors, metric), fontsize=12)

    if annotate:
        # for sample annotation
        sample_types = ["_".join(name.split('_')[:3]) for name in full_samples_names]

        # annotate points
        for i in range(len(sample_types)):
            pyplot.annotate(sample_types[i],  # this is the text
                            (embedding[i, 0], embedding[i, 1]),  # this is the point to label
                            textcoords="offset points",  # how to position the text
                            xytext=(0, 3),  # distance from text to points (x,y)
                            ha='center',  # horizontal alignment can be left, right or center
                            fontsize=6)

    pyplot.legend(title='Harm 4GHz: batches', bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0., fontsize=10)
    pyplot.tight_layout()
    pyplot.show()


def get_all_data_from_h5(path):
    """ This method parses h5 file to extract all necessary data. """

    with h5py.File(path, 'r') as f:

        ions_names = [str(name).replace('b\'', '')[0:-1] for name in list(f["annotation"]["name"])]
        ions_mzs = [float(str(mz).replace('b\'mz', '')[0:-1]) for mz in list(f["annotation"]["mzLabel"])]

        mz_axis = list(f["ions"]["mz"])
        data = f["data"][()].T
        colnames = [str(p).replace('b\'', '')[0:-1] for p in list(f["samples"]["perturbation"])]

    all_data = {
        "annotation": {"mzs": ions_mzs, "names": ions_names},
        "samples": {"data": data, "mzs": mz_axis, "names": colnames}
    }

    return all_data


def check_shared_perturbations():
    """ Check how many perturbations are done in each batch and how many are shared. """

    path = '/Users/{}/ETH/projects/normalization/data/'.format(user)

    perturbations = []
    unique_perturbations = set()

    for name in ['harm_4_0108 DATA.h5', 'harm_4_0110 DATA.h5', 'harm_4_0124 DATA.h5',
                 'harm_4_0219 DATA.h5', 'harm_4_0221 DATA.h5', 'harm_4_0304 DATA.h5',
                 'harm_4_0306 DATA.h5']:

        data = get_all_data_from_h5(path + name)

        print()
        print('processing {}'.format(name))
        print('n perturbations = {}'.format(set(data['samples']['names']).__len__()))

        perturbations.append(list(set(data['samples']['names'])))
        unique_perturbations.update(list(set(data['samples']['names'])))

    common_perturbations = []
    for up in list(unique_perturbations):
        # make sure it exists in all batches
        exists_in_all_batches = sum([up in batch for batch in perturbations]) == 7
        if exists_in_all_batches:
            common_perturbations.append(up)

    print("total shared perturbations for 7 batches: {}".format(len(common_perturbations)))
    print(common_perturbations)


def get_shared_perturbations_ids_for_batch(batch):

    ids = []
    names = []

    for sp in sps:
        # get ids of shared perturbations in this batch
        sp_ids = numpy.where(numpy.array(batch['data']['samples']['names']) == sp)[0].tolist()

        ids.extend(sp_ids)  # add ids
        names.extend([sp + '_' + batch['id'] + '_' + str(i) for i in range(len(sp_ids))])  # add names (perturbation + batch + replicate)

    return ids, names


def collapse_same_mzs(all_data, precision=2):
    """ Every ion has >6 digits of precision, though annotation has precision of 2-3 digit.
        E.g.:
            57.03213    - Acetone
            57.0328315  - Acetone
            57.03221421 - Acetone
            57.03256512 - Acetone

        This method collapses this to 57.03 - Acetone in the 7-batch dataset supplied.
    """

    intensities = all_data.iloc[:, 3:].values

    round_mz = numpy.round(all_data.mz.values, precision)
    unique_round_mz = numpy.unique(round_mz)

    new_data = pandas.DataFrame()
    for mz in unique_round_mz:
        indices = numpy.where(round_mz == mz)[0]
        summed_intensities = intensities[indices, :].sum(axis=0)

        u_names = numpy.unique(all_data.name.values[indices])
        merged_entry_meta = pandas.DataFrame({'name': "__".join(u_names), 'mz': [mz], 'rt': [1]})
        merged_entry_data = pandas.DataFrame([summed_intensities], columns=all_data.columns[3:])
        merged_entry = pandas.concat([merged_entry_meta, merged_entry_data], axis=1)

        new_data = pandas.concat([new_data, merged_entry], ignore_index=True)

    return new_data


def merge_batches_and_save_dataset():
    """ It gets all batches, merges mz axis
        and makes a single dataset of shared perturbations (samples with spike-ins). """

    path = '/Users/andreidm/ETH/projects/normalization/data/'

    batches = []
    merged_mz = set()

    for bid in bids:

        data = get_all_data_from_h5(path + 'harm_4_{}_DATA.h5'.format(bid))
        batches.append({'data': data, 'id': bid})
        merged_mz.update(data['samples']['mzs'])

    merged_mz = sorted(list(merged_mz))
    annotation = []

    shared_mz_df = pandas.DataFrame()
    for mz in merged_mz:

        mz_df = pandas.DataFrame()
        for batch in batches:

            columns, names = get_shared_perturbations_ids_for_batch(batch)

            if mz in batch['data']['samples']['mzs']:
                # if this mz appears in batch, use intensities
                index = batch['data']['samples']['mzs'].index(mz)
                bdf = pandas.DataFrame([batch['data']['samples']['data'][index, columns]], columns=names)

                # each mz appears in one batch only, so annotation can be assigned only here
                anno_index = batch['data']['annotation']['mzs'].index(round(mz, 4))
                annotation.append(batch['data']['annotation']['names'][anno_index])
            else:
                # if not, fill up with zeros
                bdf = pandas.DataFrame([numpy.zeros(len(columns))], columns=names)

            mz_df = pandas.concat([mz_df, bdf], axis=1)

        shared_mz_df = pandas.concat([shared_mz_df, mz_df], ignore_index=True)

    assert len(merged_mz) == len(annotation)

    all_data = pandas.DataFrame({'name': annotation, 'mz': merged_mz, 'rt': [0 for x in merged_mz]})
    all_data = pandas.concat([all_data, shared_mz_df], axis=1)

    # collapse the same mzs
    all_data = collapse_same_mzs(all_data)

    # filter out small intensities
    filtered_data = all_data[(all_data.iloc[:, 3:] > min_relevant_intensity).all(axis=1)]

    # save
    all_data.to_csv(path + "all_data.csv", index=False)
    filtered_data.to_csv(path + "filtered_data.csv", index=False)


def generate_batch_info(file, path='/Users/andreidm/ETH/projects/normalization/data/'):
    """ Creates batch info file in format:

        sample.name, injection.order, batch, group,class \n
        QC1, 1, 1, QC, QC\n
        A1, 2, 1, 0, Subject\n
        A2, 3, 1, 1, Subject\n
        A3, 4, 1, 1, Subject\n
        QC2, 5, 2, QC, QC\n
        A4, 6, 2, 0, Subject\n
        A5, 7, 2, 1, Subject\n
        A6, 8, 2, 1, Subject\n

        This was done for NormAE.
    """

    data = pandas.read_csv(path + file)

    full_samples_names = data.columns.values[3:]

    injections = [1 for x in full_samples_names]

    batches = [bids.index(name.split('_')[3]) + 1 for name in full_samples_names]

    groups = []
    for name in full_samples_names:
        group = 'QC' if "_".join(name.split('_')[:3]) in controls else '1'
        groups.append(group)

    classes = []
    for name in full_samples_names:
        class_ = 'QC' if "_".join(name.split('_')[:3]) in controls else 'Subject'
        classes.append(class_)

    batch_information = pandas.DataFrame({'sample.name': full_samples_names,
                                          'injection.order': injections,
                                          'batch': batches,
                                          'group': groups,
                                          'class': classes})

    batch_information.to_csv(path + 'batch_info.csv', index=False)


def implement_pipeline():
    """ A collection of retrospective steps. """

    path = '/Users/andreidm/ETH/projects/normalization/data/'

    # check which samples / perturbations are common for each batch
    check_shared_perturbations()

    # collect and merge batches along mz axis
    merge_batches_and_save_dataset()

    # collect merged dataset
    data = pandas.read_csv(path + 'all_data.csv')
    # perform PCA to reduce from 2800+ to 30 variables preserving >90% of variation
    reduced_data, _ = run_pca(data.iloc[:, 3:].values.T)
    # run UMAP to see batch effects and clustering
    run_umap(reduced_data[:, :30], data.columns.values[3:], neighbors=100, metric='correlation', scale=True, annotate=True)

    # collect filtered dataset
    filtered_data = pandas.read_csv(path + 'filtered_data.csv')
    # no PCA happening, since the dataset is much smaller
    # run UMAP to see batch effects
    run_umap(filtered_data.values[:, 3:].T, filtered_data.columns.values[3:], neighbors=100, metric='correlation', scale=True, annotate=True)

    # generate file with batch information
    generate_batch_info('filtered_data.csv', path=path)


def get_injection_order_and_names():
    """ Dumb and ugly method to retrieve injection order from h5 files:
        :returns two lists of samples names and order indices"""

    path = '/Users/{}/ETH/projects/normalization/data/raw/'.format(user)

    inj_order_types = []
    inj_order_batches = []

    # collect all names
    for bid in bids:
        data = get_all_data_from_h5(path + 'harm_4_{}_DATA.h5'.format(bid))

        sp_types = [x for x in data['samples']['names'] if x in sps]

        inj_order_types.extend(sp_types)
        inj_order_batches.extend([bid for x in sp_types])

    inj_order = []
    inj_order_names = []
    # construct new names keeping injection sequence
    for i in range(len(inj_order_types)):
        inj_order_names.append('{}_{}_0'.format(inj_order_types[i], inj_order_batches[i]))
        inj_order_names.append('{}_{}_1'.format(inj_order_types[i], inj_order_batches[i]))
        inj_order_names.append('{}_{}_2'.format(inj_order_types[i], inj_order_batches[i]))

        inj_order.append(3 * i + 1)
        inj_order.append(3 * i + 2)
        inj_order.append(3 * i + 3)

    return inj_order, inj_order_names


def edit_the_data_for_normae():
    """ This method updates the data for usage of NormAE (proper comparison) with the following:
        - rt = 0, as Nicola used,
        - only SRM_000* samples are used as QCs,
        - injection order is added as in .h5 files

        Initial data files were replaced with the new ones.
    """

    inj_order, inj_order_names = get_injection_order_and_names()

    path = '/Users/{}/ETH/projects/normalization/data/'.format(user)
    filtered_data = pandas.read_csv(path + 'filtered_data.csv')
    batch_info = pandas.read_csv(path + 'batch_info_2.csv')

    # refine meta info for NormAE input

    # SCENARIO 2: no groups at all (as if all samples were different), SRMs as QCs
    filtered_data['rt'] = 0  # as Nicola did

    batch_info['group'] = 1
    batch_info['class'] = 'Subject'

    for i in range(batch_info.shape[0]):

        sample_name = batch_info.loc[i, 'sample.name']
        # set correct order
        batch_info.loc[i, 'injection.order'] = inj_order[inj_order_names.index(sample_name)]

        if 'SRM_000' in sample_name:
            # set controls
            batch_info.loc[i, 'class'] = 'QC'

    filtered_data.to_csv(path + 'filtered_data.csv', index=False)
    batch_info.to_csv(path + 'batch_info_2.csv', index=False)


if __name__ == '__main__':

    path = '/Users/{}/ETH/projects/normalization/data/'.format(user)

    # refine batch info for NormAE input

    # SCENARIO 1: groups defined as sample types, SRMs as QCs
    batch_info = pandas.read_csv(path + 'batch_info.csv')
    for i in range(batch_info.shape[0]):

        sample_name = batch_info.loc[i, 'sample.name']

        for type in sps:
            if type in sample_name:
                batch_info.loc[i, 'group'] = sps.index(type)
                break

    batch_info.to_csv(path + 'batch_info.csv', index=False)

    # SCENARIO 2: no groups at all (as if all samples were different), SRMs as QCs
    batch_info = pandas.read_csv(path + 'batch_info_2.csv')
    batch_info['group'] = 1  # must be int
    batch_info.to_csv(path + 'batch_info_2.csv', index=False)