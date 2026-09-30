import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { ApiError } from '../../api/errors';
import type { JobOptions, Project } from '../../api/types';
import { validatePdf } from '../../model/uploads';
import { normalizePatentId } from '../../model/tasks';

export function useTaskSubmission(onCreated: (project: Project) => void) {
  const [created, setCreated] = useState<Project | null>(null);
  const [busy, setBusy] = useState<'upload' | 'start' | 'check' | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const lock = useRef(false);
  const mounted = useRef(true);
  const checkController = useRef<AbortController | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      checkController.current?.abort();
    };
  }, []);
  async function submit(input: {
    file: File | null;
    title: string;
    patentId: string;
    extract: boolean;
    options: JobOptions;
  }) {
    if (lock.current || uncertain) return;
    lock.current = true;
    setError(null);
    let next = created;
    try {
      if (!next) {
        if (!input.file) throw new Error('请选择原始专利 PDF。');
        if (!input.title.trim()) throw new Error('请输入项目名称。');
        if (input.title.trim().length > 200) throw new Error('项目名称最多 200 个字符。');
        const patentId = normalizePatentId(input.patentId);
        setBusy('upload');
        await validatePdf(input.file);
        next = await api.upload(input.file, input.title.trim(), patentId);
        if (!mounted.current) return;
        setCreated(next);
      }
      if (input.extract) {
        if ((input.options.task_note?.length ?? 0) > 2000)
          throw new Error('任务说明最多 2000 个字符。');
        setBusy('start');
        await api.createJob(next.id, null, input.options);
      }
      if (mounted.current) onCreated(next);
    } catch (e) {
      if (mounted.current) {
        setError(e instanceof Error ? e : new Error('任务提交失败。'));
        setUncertain(e instanceof ApiError && e.uncertain);
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(null);
    }
  }
  async function check() {
    if (!created || lock.current) return;
    lock.current = true;
    setBusy('check');
    setError(null);
    const controller = new AbortController();
    checkController.current = controller;
    try {
      const jobs = await api.jobs(created.id, controller.signal);
      if (!mounted.current) return;
      if (jobs.items.length) onCreated(created);
      else {
        setUncertain(false);
        setError(
          new Error('当前未查到任务。请确认服务端状态后，再手动重试启动；不会自动重放请求。'),
        );
      }
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e : new Error('状态检查失败。'));
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(null);
    }
  }
  return { created, busy, error, uncertain, submit, check };
}
