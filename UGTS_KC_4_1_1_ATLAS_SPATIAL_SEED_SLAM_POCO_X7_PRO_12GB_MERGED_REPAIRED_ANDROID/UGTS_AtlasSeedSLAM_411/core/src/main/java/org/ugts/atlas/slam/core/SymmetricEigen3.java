package org.ugts.atlas.slam.core;

final class SymmetricEigen3 {
    private SymmetricEigen3(){}
    static Vec3 smallest(double[][] input){
        double[][] a=new double[3][3],v={{1,0,0},{0,1,0},{0,0,1}};
        for(int i=0;i<3;i++)System.arraycopy(input[i],0,a[i],0,3);
        for(int iter=0;iter<32;iter++){
            int p=0,q=1;double max=Math.abs(a[0][1]);
            if(Math.abs(a[0][2])>max){p=0;q=2;max=Math.abs(a[0][2]);}
            if(Math.abs(a[1][2])>max){p=1;q=2;max=Math.abs(a[1][2]);}
            if(max<1e-12)break;
            double phi=0.5*Math.atan2(2*a[p][q],a[q][q]-a[p][p]),c=Math.cos(phi),s=Math.sin(phi);
            double app=c*c*a[p][p]-2*s*c*a[p][q]+s*s*a[q][q];
            double aqq=s*s*a[p][p]+2*s*c*a[p][q]+c*c*a[q][q];
            for(int k=0;k<3;k++)if(k!=p&&k!=q){double akp=a[k][p],akq=a[k][q];a[k][p]=a[p][k]=c*akp-s*akq;a[k][q]=a[q][k]=s*akp+c*akq;}
            a[p][p]=app;a[q][q]=aqq;a[p][q]=a[q][p]=0;
            for(int k=0;k<3;k++){double vkp=v[k][p],vkq=v[k][q];v[k][p]=c*vkp-s*vkq;v[k][q]=s*vkp+c*vkq;}
        }
        int idx=0;if(a[1][1]<a[idx][idx])idx=1;if(a[2][2]<a[idx][idx])idx=2;
        return new Vec3(v[0][idx],v[1][idx],v[2][idx]).normalized();
    }
}
