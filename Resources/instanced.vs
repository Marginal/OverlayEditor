// -*- mode: c -*-

attribute mat4 transform;
attribute float selected;

void main()
{
    gl_Position = gl_ModelViewProjectionMatrix * transformmatrix * gl_Vertex;
    gl_FrontColor = selected>0.5 ? vec4(1, 1, 1, 1 ) : vec4(1, 0.5, 1, 1);
    gl_TexCoord[0].st = vec2(gl_MultiTexCoord0.s, 1.0 - gl_MultiTexCoord0.t);	// Flip vertically
}
