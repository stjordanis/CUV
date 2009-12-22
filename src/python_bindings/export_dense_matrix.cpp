#include <string>
#include <boost/python.hpp>
#include <boost/python/extract.hpp>
#include <pyublas/numpy.hpp>
#include  <boost/type_traits/is_base_of.hpp>

#include <dev_dense_matrix.hpp>
#include <host_dense_matrix.hpp>
#include <convert.hpp>

using namespace std;
using namespace boost::python;
using namespace cuv;
namespace ublas = boost::numeric::ublas;

/*
 * translate our storage type to the one of ublas
 */
template<class T>
struct matrix2ublas_traits                       { typedef ublas::row_major storage_type; };
template<>
struct matrix2ublas_traits<cuv::column_major>    { typedef ublas::column_major storage_type; };
template<>
struct matrix2ublas_traits<cuv::row_major>       { typedef ublas::row_major storage_type; };

template<class T>
struct ublas2matrix_traits                                       { typedef ublas::row_major storage_type; };
template<>
struct ublas2matrix_traits<boost::numeric::ublas::column_major > { typedef cuv::column_major storage_type; };
template<>
struct ublas2matrix_traits<boost::numeric::ublas::row_major >    { typedef cuv::row_major storage_type; };

/*
 * Create VIEWs at the same location in memory
 */
template<class T,class S>
host_vector<T, S> *
vec_view(pyublas::numpy_vector<T> v){
	return new host_vector<T>(v.size(),v.as_ublas().data().data(),true);
}
template<class T, class Mto, class Mfrom>
host_dense_matrix<T, Mto>*
mat_view(pyublas::numpy_matrix<T, Mfrom> m){
	host_vector<T>* vec = new host_vector<T>(m.size1()*m.size2(),m.as_ublas().data().data(),true);
	const bool same = boost::is_same<Mto, typename ublas2matrix_traits<Mfrom>::storage_type >::value;
	if(same) return new host_dense_matrix<T,Mto>(m.size1(), m.size2(), vec);
	else     return new host_dense_matrix<T,Mto>(m.size2(), m.size1(), vec);
}
template<class T, class Mto, class Mfrom>
host_dense_matrix<T, Mto>*
copy(pyublas::numpy_matrix<T, boost::numeric::ublas::column_major> m){
	const bool same = boost::is_same<Mto, typename ublas2matrix_traits<Mfrom>::storage_type >::value;
	host_dense_matrix<T,Mto>* mat;
	if(same) new host_dense_matrix<T,Mto>(m.size1(), m.size2());
	else     new host_dense_matrix<T,Mto>(m.size2(), m.size1());
    memcpy(mat->ptr(), m.as_ublas().data().data(), mat->n() * sizeof(T));
    return mat;
}

template<class T>
void
export_dense_matrix_common(std::string name){
	typedef T mat;
	typedef typename mat::value_type value_type;
	typedef typename mat::index_type index_type;
	typedef typename mat::vec_type   vec_type;

	class_<mat>(name.c_str(), init<typename mat::index_type, typename mat::index_type>())
		.def("w",      &mat::w, "width of matrix")
		.def("h",      &mat::h, "height of matrix")
		.def("n",      &mat::n, "matrix number of elements")
		.def("__len__",&mat::n, "matrix number of elements")
		.def("memsize",&mat::memsize, "size of vector in memory (bytes)")
		.def("alloc",  &mat::alloc, "allocate memory")
		.def("dealloc",&mat::dealloc, "deallocate memory")
		.def("vec",    (vec_type* (mat::*)())(&mat::vec_ptr), "internal memory vector", return_internal_reference<>())
		.def("at",    (value_type (mat::*)(const index_type&,const index_type&))(&mat::operator()), "value at this position")
		;
}

template <class T, class M, class M2>
void
export_dense_matrix_pushpull(std::string typen){
	export_dense_matrix_common<dev_dense_matrix<T, M> >  ( std::string( "dev_matrix_" ) + (typen));
	export_dense_matrix_common<host_dense_matrix<T, M2> >( std::string( "host_matrix_" ) + (typen));
	def("convert", (void(*)(dev_dense_matrix<T,M>&,const host_dense_matrix<T,M2>&)) cuv::convert);
	def("convert", (void(*)(host_dense_matrix<T,M2>&,const dev_dense_matrix<T,M>&)) cuv::convert);
}
template <class T, class Mfrom, class Mto>
void
export_dense_matrix_view(const char* str){
	typedef host_dense_matrix<T,Mto>                          to_type;            // destination type
	typedef typename matrix2ublas_traits<Mfrom>::storage_type Mfrom_ublas_type;   // our column/row major type (derived from ublas)
	typedef pyublas::numpy_matrix<T,Mfrom_ublas_type>         from_type;          // source data type
	typedef to_type* (*func_type)(from_type)                  ;
	def(str,     (func_type) (mat_view<T,Mto,Mfrom_ublas_type>),return_value_policy<manage_new_object>());
}
template <class T>
void
export_dense_matrix_views(){
	export_dense_matrix_view<T,column_major,column_major>("view_cm");
	export_dense_matrix_view<T,column_major,row_major>("view_rm");
	export_dense_matrix_view<T,row_major,column_major>("view_cm");
	export_dense_matrix_view<T,row_major,row_major>("view_rm");
}

template<class T, class Mfrom, class Mto>
dev_dense_matrix<T,Mto>*
numpy2dev_dense_mat(pyublas::numpy_matrix<T, Mfrom> m){
	dev_dense_matrix<T,Mto>* to = new dev_dense_matrix<T,Mto>(1,1);
	host_dense_matrix<T,Mto>* from = mat_view<T,Mto,Mfrom>(m);
	convert(*to,*from);
	delete from;
	return to;
}
template<class T, class Mfrom, class Mto>
void export_numpy2dev_dense_mat(const char* c){
	typedef typename matrix2ublas_traits<Mfrom>::storage_type Mfrom_ublas_type;
	def(c, numpy2dev_dense_mat<T,Mfrom_ublas_type,Mto>, return_value_policy<manage_new_object>());
}
template<class T>
void
export_numpy2dev_dense_mats(){
	export_numpy2dev_dense_mat<T,column_major,column_major>("push_cm");
	export_numpy2dev_dense_mat<T,column_major,row_major>("push_rm");
	export_numpy2dev_dense_mat<T,row_major,column_major>("push_cm");
	export_numpy2dev_dense_mat<T,row_major,row_major>("push_rm");
}

void export_dense_matrix(){
	// push and pull host matrices
	export_dense_matrix_pushpull<float,column_major,column_major>("cmf");
	export_dense_matrix_pushpull<float,row_major,row_major>("rmf");

	export_dense_matrix_pushpull<signed char,column_major,column_major>("cmsc");
	export_dense_matrix_pushpull<signed char,row_major,row_major>("rmsc");

	export_dense_matrix_pushpull<unsigned char,column_major,column_major>("cmuc");
	export_dense_matrix_pushpull<unsigned char,row_major,row_major>("rmuc");

	// numpy --> host matrix
	export_dense_matrix_views<float>();
	export_dense_matrix_views<signed char>();
	export_dense_matrix_views<unsigned char>();

	// numpy --> dev matrix
	export_numpy2dev_dense_mats<float>();
	export_numpy2dev_dense_mats<signed char>();
	export_numpy2dev_dense_mats<unsigned char>();
}

