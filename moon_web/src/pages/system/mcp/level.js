export const isSuperUser = () => localStorage.getItem('is_supper') === 'true';

export const levelOptions = isSuper => [
  {value: 'normal', label: '普通 Key（拦截高危命令、限定文件目录）'},
  {value: 'super', label: '超管 Key（全部机器任意操作，不做限制）', disabled: !isSuper},
];
