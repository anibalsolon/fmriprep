#!/usr/bin/env python
# -*- coding: utf-8 -*-
# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""
fMRIprep base processing workflows
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


"""

import sys
import os
from copy import deepcopy

from niworkflows.nipype.pipeline import engine as pe
from niworkflows.nipype.interfaces import utility as niu

from ..interfaces import (
    BIDSDataGrabber, BIDSFreeSurferDir, BIDSInfo, SubjectSummary, AboutSummary,
    DerivativesDataSink
)
from ..utils.bids import collect_data
from ..utils.misc import fix_multi_T1w_source_name
from ..info import __version__

from .anatomical import init_anat_preproc_wf
from .bold import init_func_preproc_wf


def init_fmriprep_wf(subject_list, task_id, run_uuid,
                     ignore, debug, anat_only, longitudinal, omp_nthreads,
                     skull_strip_ants, work_dir, output_dir, bids_dir,
                     freesurfer, output_spaces, template, hires,
                     bold2t1w_dof, fmap_bspline, fmap_demean, use_syn, force_syn,
                     use_aroma, ignore_aroma_err, output_grid_ref,):
    fmriprep_wf = pe.Workflow(name='fmriprep_wf')
    fmriprep_wf.base_dir = work_dir

    if freesurfer:
        fsdir = pe.Node(
            BIDSFreeSurferDir(
                derivatives=output_dir,
                freesurfer_home=os.getenv('FREESURFER_HOME'),
                spaces=output_spaces),
            name='fsdir', run_without_submitting=True)

    reportlets_dir = os.path.join(work_dir, 'reportlets')
    for subject_id in subject_list:
        single_subject_wf = init_single_subject_wf(subject_id=subject_id,
                                                   task_id=task_id,
                                                   name="single_subject_" + subject_id + "_wf",
                                                   ignore=ignore,
                                                   debug=debug,
                                                   anat_only=anat_only,
                                                   longitudinal=longitudinal,
                                                   omp_nthreads=omp_nthreads,
                                                   skull_strip_ants=skull_strip_ants,
                                                   reportlets_dir=reportlets_dir,
                                                   output_dir=output_dir,
                                                   bids_dir=bids_dir,
                                                   freesurfer=freesurfer,
                                                   output_spaces=output_spaces,
                                                   template=template,
                                                   hires=hires,
                                                   bold2t1w_dof=bold2t1w_dof,
                                                   fmap_bspline=fmap_bspline,
                                                   fmap_demean=fmap_demean,
                                                   use_syn=use_syn,
                                                   force_syn=force_syn,
                                                   output_grid_ref=output_grid_ref,
                                                   use_aroma=use_aroma,
                                                   ignore_aroma_err=ignore_aroma_err)

        single_subject_wf.config['execution']['crashdump_dir'] = (
            os.path.join(output_dir, "fmriprep", "sub-" + subject_id, 'log', run_uuid)
        )
        for node in single_subject_wf._get_all_nodes():
            node.config = deepcopy(single_subject_wf.config)
        if freesurfer:
            fmriprep_wf.connect(fsdir, 'subjects_dir',
                                single_subject_wf, 'inputnode.subjects_dir')
        else:
            fmriprep_wf.add_nodes([single_subject_wf])

    return fmriprep_wf


def init_single_subject_wf(subject_id, task_id, name,
                           ignore, debug, anat_only, longitudinal, omp_nthreads,
                           skull_strip_ants, reportlets_dir, output_dir, bids_dir,
                           freesurfer, output_spaces, template, hires,
                           bold2t1w_dof, fmap_bspline, fmap_demean, use_syn, force_syn,
                           output_grid_ref, use_aroma, ignore_aroma_err):
    """
    The adaptable fMRI preprocessing workflow
    """

    if name == 'single_subject_wf':
        # for documentation purposes
        subject_data = {
            't1w': ['/completely/made/up/path/sub-01_T1w.nii.gz'],
            'bold': ['/completely/made/up/path/sub-01_task-nback_bold.nii.gz']
        }
        layout = None
    else:
        subject_data, layout = collect_data(bids_dir, subject_id, task_id)

    # Make sure we always go through these two checks
    if not anat_only and subject_data['bold'] == []:
        raise Exception("No BOLD images found for participant {} and task {}. "
                        "All workflows require BOLD images.".format(
                            subject_id, task_id if task_id else '<all>'))

    if not subject_data['t1w']:
        raise Exception("No T1w images found for participant {}. "
                        "All workflows require T1w images.".format(subject_id))

    workflow = pe.Workflow(name=name)

    inputnode = pe.Node(niu.IdentityInterface(fields=['subjects_dir']),
                        name='inputnode')

    bidssrc = pe.Node(BIDSDataGrabber(subject_data=subject_data, anat_only=anat_only),
                      name='bidssrc')

    bids_info = pe.Node(BIDSInfo(), name='bids_info', run_without_submitting=True)

    summary = pe.Node(SubjectSummary(output_spaces=output_spaces, template=template),
                      name='summary', run_without_submitting=True)

    about = pe.Node(AboutSummary(version=__version__,
                                 command=' '.join(sys.argv)),
                    name='about', run_without_submitting=True)

    ds_summary_report = pe.Node(
        DerivativesDataSink(base_directory=reportlets_dir,
                            suffix='summary'),
        name='ds_summary_report', run_without_submitting=True)

    ds_about_report = pe.Node(
        DerivativesDataSink(base_directory=reportlets_dir,
                            suffix='about'),
        name='ds_about_report', run_without_submitting=True)

    # Preprocessing of T1w (includes registration to MNI)
    anat_preproc_wf = init_anat_preproc_wf(name="anat_preproc_wf",
                                           skull_strip_ants=skull_strip_ants,
                                           output_spaces=output_spaces,
                                           template=template,
                                           debug=debug,
                                           longitudinal=longitudinal,
                                           omp_nthreads=omp_nthreads,
                                           freesurfer=freesurfer,
                                           hires=hires,
                                           reportlets_dir=reportlets_dir,
                                           output_dir=output_dir)

    workflow.connect([
        (inputnode, anat_preproc_wf, [('subjects_dir', 'inputnode.subjects_dir')]),
        (bidssrc, bids_info, [(('t1w', fix_multi_T1w_source_name), 'in_file')]),
        (inputnode, summary, [('subjects_dir', 'subjects_dir')]),
        (bidssrc, summary, [('t1w', 't1w'),
                            ('t2w', 't2w'),
                            ('bold', 'bold')]),
        (bids_info, summary, [('subject_id', 'subject_id')]),
        (bidssrc, anat_preproc_wf, [('t1w', 'inputnode.t1w'),
                                    ('t2w', 'inputnode.t2w')]),
        (summary, anat_preproc_wf, [('subject_id', 'inputnode.subject_id')]),
        (bidssrc, ds_summary_report, [(('t1w', fix_multi_T1w_source_name), 'source_file')]),
        (summary, ds_summary_report, [('out_report', 'in_file')]),
        (bidssrc, ds_about_report, [(('t1w', fix_multi_T1w_source_name), 'source_file')]),
        (about, ds_about_report, [('out_report', 'in_file')]),
    ])

    if anat_only:
        return workflow

    for bold_file in subject_data['bold']:
        func_preproc_wf = init_func_preproc_wf(bold_file=bold_file,
                                               layout=layout,
                                               ignore=ignore,
                                               freesurfer=freesurfer,
                                               bold2t1w_dof=bold2t1w_dof,
                                               reportlets_dir=reportlets_dir,
                                               output_spaces=output_spaces,
                                               template=template,
                                               output_dir=output_dir,
                                               omp_nthreads=omp_nthreads,
                                               fmap_bspline=fmap_bspline,
                                               fmap_demean=fmap_demean,
                                               use_syn=use_syn,
                                               force_syn=force_syn,
                                               debug=debug,
                                               output_grid_ref=output_grid_ref,
                                               use_aroma=use_aroma,
                                               ignore_aroma_err=ignore_aroma_err)

        workflow.connect([
            (anat_preproc_wf, func_preproc_wf,
             [('outputnode.t1_preproc', 'inputnode.t1_preproc'),
              ('outputnode.t1_brain', 'inputnode.t1_brain'),
              ('outputnode.t1_mask', 'inputnode.t1_mask'),
              ('outputnode.t1_seg', 'inputnode.t1_seg'),
              ('outputnode.t1_tpms', 'inputnode.t1_tpms'),
              ('outputnode.t1_2_mni_forward_transform', 'inputnode.t1_2_mni_forward_transform'),
              ('outputnode.t1_2_mni_reverse_transform', 'inputnode.t1_2_mni_reverse_transform')])
        ])

        if freesurfer:
            workflow.connect([
                (anat_preproc_wf, func_preproc_wf,
                 [('outputnode.subjects_dir', 'inputnode.subjects_dir'),
                  ('outputnode.subject_id', 'inputnode.subject_id'),
                  ('outputnode.fs_2_t1_transform', 'inputnode.fs_2_t1_transform')]),
            ])

    return workflow
